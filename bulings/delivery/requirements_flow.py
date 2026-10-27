from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from bulings.delivery.archive import archive_dir, archive_rel_path
from bulings.delivery.documents import assert_fresh, read_managed_document
from bulings.delivery.errors import DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.paths import document_id
from bulings.delivery.time_util import format_iso8601
from bulings.install import is_unity_project

NowFn = Callable[[], datetime]

REQUIREMENTS_REL = "01-requirements/README.md"
TERMINOLOGY_REL = "01-requirements/terminology.md"
SCENE_FIELDS = ("主体", "初始条件", "操作", "可观察结果", "来源")
PENDING_SOURCE_PREFIX = "待提供"


@dataclass(frozen=True)
class ColdReadPromptResult:
    feature_id: str
    role: str
    prompt: str
    materials: list[str]


def compute_requirements_approval_state(
    archive_path: Path,
    feature_id: str,
    feature_meta: dict[str, object],
) -> str:
    approval = feature_meta.get("approvals")
    if not isinstance(approval, dict):
        return "missing"
    record = approval.get("requirements")
    if not isinstance(record, dict):
        return "missing"
    decision = record.get("decision")
    if decision not in {"approve", "reject"}:
        return "missing"

    overview_id = document_id(feature_id, "requirements.overview")
    term_id = document_id(feature_id, "requirements.terminology")
    try:
        overview_meta, _ = read_managed_document(archive_path / REQUIREMENTS_REL)
        term_meta, _ = read_managed_document(archive_path / TERMINOLOGY_REL)
    except DeliveryError:
        return "stale"

    if str(record.get("fingerprint")) != str(overview_meta.get("fingerprint")):
        return "stale"
    if str(record.get("semanticVersion")) != str(overview_meta.get("semanticVersion")):
        return "stale"
    term_fp = record.get("terminologyFingerprint")
    if term_fp is not None and str(term_fp) != str(term_meta.get("fingerprint")):
        return "stale"
    return "approved" if decision == "approve" else "rejected"


def cold_read_prompt(project_root: Path, feature_id: str, question: str) -> ColdReadPromptResult:
    project_root = project_root.resolve()
    _validate_feature_id(feature_id)
    _validate_project(project_root)
    normalized_question = question.strip()
    if not normalized_question:
        raise DeliveryError(code="INVALID_QUESTION", message="--question 不能为空", exit_code=2)

    archive = archive_dir(project_root, feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")

    _meta, body = read_managed_document(archive / REQUIREMENTS_REL)
    if "待填写" in body or "## 场景" not in body or not _has_scene_heading(body):
        raise DeliveryError(code="MATERIAL_MISSING", message="需求总览尚未就绪", exit_code=1)

    rel_archive = archive_rel_path(feature_id)
    materials = [
        f"{rel_archive}/{REQUIREMENTS_REL}",
        f"{rel_archive}/{TERMINOLOGY_REL}",
    ]
    prompt = _build_cold_read_prompt(normalized_question, materials)

    return ColdReadPromptResult(
        feature_id=feature_id,
        role="cold-read",
        prompt=prompt,
        materials=materials,
    )


def approve_requirements(
    project_root: Path,
    feature_id: str,
    decision: str,
    locator: str,
    user_confirmation: str,
    *,
    now: NowFn | None = None,
) -> dict[str, object]:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    project_root = project_root.resolve()
    _validate_feature_id(feature_id)
    _validate_project(project_root)

    if decision not in {"approve", "reject"}:
        raise DeliveryError(code="INVALID_DECISION", message="--decision 必须为 approve 或 reject", exit_code=2)

    loc = locator.strip()
    confirmation = user_confirmation.strip()
    if not loc or not confirmation:
        raise DeliveryError(code="INVALID_CONFIRMATION", message="locator 与 user-confirmation 不能为空", exit_code=2)

    archive = archive_dir(project_root, feature_id)
    feature_path = archive / "feature.json"
    feature_meta = dict(read_feature_meta(feature_path))
    lifecycle = feature_meta.get("lifecycle")
    if lifecycle not in {"draft", "active"}:
        raise DeliveryError(code="INVALID_LIFECYCLE", message="当前生命周期不允许批准需求", exit_code=1)

    overview_id = document_id(feature_id, "requirements.overview")
    term_id = document_id(feature_id, "requirements.terminology")
    try:
        assert_fresh(project_root, feature_id, [overview_id, term_id])
    except DeliveryError as error:
        raise DeliveryError(
            code=error.code,
            message=error.message,
            exit_code=error.exit_code,
            blockers=error.blockers,
        ) from error

    _meta, body = read_managed_document(archive / REQUIREMENTS_REL)
    validate_requirements_for_approve(project_root, archive, body)

    overview_meta, _ = read_managed_document(archive / REQUIREMENTS_REL)
    term_meta, _ = read_managed_document(archive / TERMINOLOGY_REL)

    stamp = format_iso8601(now_fn())
    record = {
        "decision": decision,
        "documentId": overview_id,
        "semanticVersion": str(overview_meta.get("semanticVersion", "0.1.0")),
        "fingerprint": str(overview_meta.get("fingerprint")),
        "terminologyFingerprint": str(term_meta.get("fingerprint")),
        "locator": loc,
        "userConfirmation": confirmation,
        "confirmedAt": stamp,
    }

    approvals = feature_meta.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    else:
        approvals = dict(approvals)
    approvals["requirements"] = record
    feature_meta["approvals"] = approvals
    if decision == "approve" and lifecycle == "draft":
        feature_meta["lifecycle"] = "active"
    feature_meta["updatedAt"] = stamp

    before_bytes = feature_path.read_bytes()
    try:
        temp_path = feature_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(feature_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(temp_path, feature_path)
    except Exception:
        feature_path.write_bytes(before_bytes)
        raise

    return record


def validate_requirements_for_approve(project_root: Path, archive: Path, body: str) -> None:
    errors = validate_requirements_structure(project_root, archive, body, for_approve=True)
    if errors:
        raise DeliveryError(
            code="INVALID_REQUIREMENTS",
            message=errors[0],
            exit_code=1,
        )


def validate_requirements_structure(
    project_root: Path,
    archive: Path,
    body: str,
    *,
    for_approve: bool,
) -> list[str]:
    errors: list[str] = []
    if "# 需求" not in body.splitlines()[0:3]:
        errors.append("缺少一级标题「需求」")
    if "## 当前决定" not in body:
        errors.append("缺少「当前决定」")
    if "## 场景" not in body:
        errors.append("缺少「场景」")
    if "## 非目标" not in body:
        errors.append("缺少「非目标」")

    scenes = _parse_scenes(body)
    if not scenes:
        errors.append("至少需要一个场景")
        return errors

    names = [scene.name for scene in scenes]
    if len(names) != len(set(names)):
        errors.append("场景名重复")

    for scene in scenes:
        for field in SCENE_FIELDS:
            value = scene.fields.get(field, "").strip()
            if not value:
                errors.append(f"场景「{scene.name}」缺少{field}")
        source = scene.fields.get("来源", "").strip()
        if for_approve and source.startswith(PENDING_SOURCE_PREFIX):
            errors.append("来源仍为待提供")
        elif for_approve and source and not source.startswith(PENDING_SOURCE_PREFIX):
            path_part = source.split("#", 1)[0].strip()
            if path_part and not (project_root / path_part).is_file():
                errors.append(f"来源文件不存在: {path_part}")
    return errors


@dataclass
class _Scene:
    name: str
    fields: dict[str, str]


def _parse_scenes(body: str) -> list[_Scene]:
    lines = body.splitlines()
    scenes: list[_Scene] = []
    in_scenarios = False
    current: _Scene | None = None
    for line in lines:
        if line.strip() == "## 场景":
            in_scenarios = True
            continue
        if line.startswith("## ") and in_scenarios:
            break
        if not in_scenarios:
            continue
        if line.startswith("### "):
            if current is not None:
                scenes.append(current)
            current = _Scene(name=line[4:].strip(), fields={})
            continue
        if current is None:
            continue
        for field in SCENE_FIELDS:
            if line.strip().startswith(f"- {field}：") or line.strip().startswith(f"- {field}:"):
                parts = re.split(r"[：:]", line.strip()[2:].strip(), maxsplit=1)
                if len(parts) == 2:
                    current.fields[field] = parts[1].strip()
    if current is not None:
        scenes.append(current)
    return scenes


def _has_scene_heading(body: str) -> bool:
    return any(line.startswith("### ") for line in body.splitlines())


def list_requirement_scene_names(body: str) -> list[str]:
    return [scene.name for scene in _parse_scenes(body)]


def _build_cold_read_prompt(question: str, materials: list[str]) -> str:
    material_lines = "\n".join(f"- {item}" for item in materials)
    markers = "「直接说明」「只能推断」「没有说明」「存在歧义」"
    return (
        "你是冷读角色。只根据下列 materials 中的正式材料回答入口问题，不要使用对话外的记忆，"
        "不要读取实施目录，不要根据常识补全，不要修改任何文件。\n\n"
        f"materials：\n{material_lines}\n\n"
        f"入口问题（原文）：\n{question}\n\n"
        f"请把每个结论标成 {markers} 之一。"
    )


def _validate_project(project_root: Path) -> None:
    if not is_unity_project(project_root):
        raise DeliveryError(
            code="NOT_UNITY_PROJECT",
            message=f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {project_root}",
            exit_code=1,
        )


def _validate_feature_id(feature_id: str) -> None:
    if not is_valid_feature_id(feature_id):
        raise DeliveryError(code="INVALID_FEATURE_ID", message="feature-id 不合法", exit_code=2)
