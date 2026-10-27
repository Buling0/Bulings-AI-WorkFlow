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
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.frontmatter import render_frontmatter
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import (
    REQUIREMENTS_REL,
    compute_requirements_approval_state,
    list_requirement_scene_names,
)
from bulings.delivery.time_util import format_iso8601
from bulings.install import is_unity_project

NowFn = Callable[[], datetime]

INVESTIGATION_REL = "02-investigation/README.md"
DESIGN_REL = "03-design/README.md"
CHANGE_TYPES = frozenset({"内部整理", "外部行为"})


@dataclass(frozen=True)
class DesignReviewPromptResult:
    feature_id: str
    role: str
    prompt: str
    materials: list[str]


def compute_architecture_approval_state(
    archive_path: Path,
    feature_id: str,
    feature_meta: dict[str, object],
) -> str:
    req_state = compute_requirements_approval_state(archive_path, feature_id, feature_meta)
    if req_state == "stale":
        return "stale"

    approval = feature_meta.get("approvals")
    if not isinstance(approval, dict):
        return "missing"
    record = approval.get("architecture")
    if not isinstance(record, dict):
        return "missing"
    decision = record.get("decision")
    if decision not in {"pass", "fail", "unverified"}:
        return "missing"

    try:
        design_meta, _ = read_managed_document(archive_path / DESIGN_REL)
    except DeliveryError:
        return "stale"

    if str(record.get("fingerprint")) != str(design_meta.get("fingerprint")):
        return "stale"
    if str(record.get("semanticVersion")) != str(design_meta.get("semanticVersion")):
        return "stale"
    return str(decision)


def investigation_has_blocking_unknowns(body: str) -> bool:
    for item in _parse_unknowns(body):
        blocking = item.fields.get("阻塞", "").strip()
        if blocking == "是":
            return True
    return False


def design_has_external_behavior(body: str) -> bool:
    for change in _parse_design_changes(body):
        if change.fields.get("类型", "").strip() == "外部行为":
            return True
    return False


def prepare_design(project_root: Path, feature_id: str, *, now: NowFn | None = None) -> str:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    project_root, archive, feature_meta = _load_context(project_root, feature_id)
    _require_requirements_approved(archive, feature_id, feature_meta)
    _require_investigation_not_blocked(archive)

    req_id = document_id(feature_id, "requirements.overview")
    inv_id = document_id(feature_id, "investigation.overview")
    design_id = document_id(feature_id, "design.overview")

    req_meta, _ = read_managed_document(archive / REQUIREMENTS_REL)
    inv_meta, _ = read_managed_document(archive / INVESTIGATION_REL)
    design_meta, design_body = read_managed_document(archive / DESIGN_REL)

    expected_deps = [req_id, inv_id]
    expected_versions = {
        req_id: str(req_meta.get("semanticVersion", "0.1.0")),
        inv_id: str(inv_meta.get("semanticVersion", "0.1.0")),
    }
    current_deps = _string_list(design_meta.get("dependencies"))
    current_versions = _string_dict(design_meta.get("dependencyVersions"))

    if current_deps == expected_deps and current_versions == expected_versions:
        return "unchanged"

    new_meta = dict(design_meta)
    new_meta["dependencies"] = expected_deps
    new_meta["dependencyVersions"] = expected_versions
    normalized_body = design_body if design_body.startswith("\n") else "\n" + design_body
    design_path = archive / DESIGN_REL
    _atomic_write_files(
        {
            design_path: render_frontmatter(new_meta, normalized_body),
            archive / "feature.json": _feature_json_with_updated_at(feature_meta, now_fn),
        }
    )
    return "prepared"


def design_review_prompt(project_root: Path, feature_id: str) -> DesignReviewPromptResult:
    project_root, archive, feature_meta = _load_context(project_root, feature_id)
    _require_requirements_approved(archive, feature_id, feature_meta)
    _require_investigation_not_blocked(archive)

    req_id = document_id(feature_id, "requirements.overview")
    inv_id = document_id(feature_id, "investigation.overview")
    design_id = document_id(feature_id, "design.overview")
    assert_fresh(project_root, feature_id, [req_id, inv_id, design_id])

    _meta, design_body = read_managed_document(archive / DESIGN_REL)
    if "待填写" in design_body:
        raise DeliveryError(code="MATERIAL_MISSING", message="设计总览尚未就绪", exit_code=1)
    if not design_has_external_behavior(design_body):
        raise DeliveryError(code="REVIEW_NOT_REQUIRED", message="不存在外部行为变化，无需设计评审", exit_code=1)

    rel_archive = archive_rel_path(feature_id)
    materials = [
        f"{rel_archive}/{REQUIREMENTS_REL}",
        f"{rel_archive}/{INVESTIGATION_REL}",
        f"{rel_archive}/{DESIGN_REL}",
    ]
    prompt = _build_design_review_prompt(materials)
    return DesignReviewPromptResult(feature_id=feature_id, role="design-review", prompt=prompt, materials=materials)


def record_design_review(
    project_root: Path,
    feature_id: str,
    decision: str,
    summary: str,
    *,
    now: NowFn | None = None,
) -> dict[str, object]:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    project_root, archive, feature_meta = _load_context(project_root, feature_id)
    if investigation_has_blocking_unknowns(read_managed_document(archive / INVESTIGATION_REL)[1]):
        raise DeliveryError(code="INVESTIGATION_BLOCKED", message="调查仍有阻塞未知", exit_code=1)

    if decision not in {"pass", "fail", "unverified"}:
        raise DeliveryError(code="INVALID_DECISION", message="decision 必须为 pass、fail 或 unverified", exit_code=2)
    normalized_summary = summary.strip()
    if not normalized_summary:
        raise DeliveryError(code="INVALID_SUMMARY", message="summary 不能为空", exit_code=2)

    design_id = document_id(feature_id, "design.overview")
    design_meta, _ = read_managed_document(archive / DESIGN_REL)
    stamp = format_iso8601(now_fn())
    record = {
        "decision": decision,
        "documentId": design_id,
        "semanticVersion": str(design_meta.get("semanticVersion", "0.1.0")),
        "fingerprint": str(design_meta.get("fingerprint")),
        "summary": normalized_summary,
        "confirmedAt": stamp,
    }
    approvals = feature_meta.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    else:
        approvals = dict(approvals)
    approvals["architecture"] = record
    feature_meta = dict(feature_meta)
    feature_meta["approvals"] = approvals
    feature_meta["updatedAt"] = stamp
    feature_path = archive / "feature.json"
    before = feature_path.read_bytes()
    try:
        temp = feature_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(feature_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(temp, feature_path)
    except Exception:
        feature_path.write_bytes(before)
        raise
    return record


def design_ready(project_root: Path, feature_id: str) -> dict[str, str]:
    project_root, archive, feature_meta = _load_context(project_root, feature_id)
    blockers: list[Blocker] = []

    req_state = compute_requirements_approval_state(archive, feature_id, feature_meta)
    if req_state != "approved":
        blockers.append(
            Blocker(code="REQUIREMENTS_NOT_APPROVED", message=f"需求批准状态: {req_state}", path="requirements")
        )

    if investigation_has_blocking_unknowns(read_managed_document(archive / INVESTIGATION_REL)[1]):
        blockers.append(Blocker(code="INVESTIGATION_BLOCKED", message="调查存在阻塞未知", path=INVESTIGATION_REL))

    req_id = document_id(feature_id, "requirements.overview")
    inv_id = document_id(feature_id, "investigation.overview")
    design_id = document_id(feature_id, "design.overview")
    try:
        assert_fresh(project_root, feature_id, [req_id, inv_id, design_id])
    except DeliveryError as error:
        for item in error.blockers:
            blockers.append(item)
        if not error.blockers:
            blockers.append(Blocker(code=error.code, message=error.message))

    _meta, design_body = read_managed_document(archive / DESIGN_REL)
    errors = validate_design_structure(project_root, archive, design_body)
    if errors:
        blockers.append(Blocker(code="INVALID_DESIGN", message=errors[0], path=DESIGN_REL))

    if design_has_external_behavior(design_body):
        arch_state = compute_architecture_approval_state(archive, feature_id, feature_meta)
        if arch_state != "pass":
            blockers.append(
                Blocker(
                    code="ARCHITECTURE_NOT_APPROVED",
                    message=f"架构评审状态: {arch_state}",
                    path="approvals.architecture",
                )
            )

    if blockers:
        raise DeliveryError(
            code="NOT_READY",
            message="设计尚未就绪",
            exit_code=1,
            blockers=blockers,
        )
    return {"status": "ready"}


def validate_investigation_structure(project_root: Path, body: str) -> list[str]:
    errors: list[str] = []
    if "# 调查" not in body:
        errors.append("缺少一级标题「调查」")
    if "## 事实" not in body:
        errors.append("缺少「事实」")
    if "## 未知" not in body:
        errors.append("缺少「未知」")
    facts = _parse_facts(body)
    for fact in facts:
        evidence = fact.fields.get("证据", "").strip()
        note = fact.fields.get("说明", "").strip()
        if not evidence:
            errors.append(f"事实「{fact.name}」缺少证据")
        if not note:
            errors.append(f"事实「{fact.name}」缺少说明")
        if evidence:
            path_part = evidence.split("#", 1)[0].strip()
            if path_part and not (project_root / path_part).is_file():
                errors.append(f"证据文件不存在: {path_part}")
    unknown_section = _unknown_section_text(body)
    if unknown_section.strip() == "无":
        return errors
    unknowns = _parse_unknowns(body)
    for item in unknowns:
        if not item.fields.get("影响", "").strip():
            errors.append(f"未知「{item.name}」缺少影响")
        if item.fields.get("阻塞", "").strip() not in {"是", "否"}:
            errors.append(f"未知「{item.name}」阻塞必须为是或否")
    return errors


def validate_design_structure(project_root: Path, archive: Path, body: str) -> list[str]:
    errors: list[str] = []
    if "# 设计" not in body:
        errors.append("缺少一级标题「设计」")
    if "## 方案" not in body:
        errors.append("缺少「方案」")
    if "## 变化" not in body:
        errors.append("缺少「变化」")
    req_body = read_managed_document(archive / REQUIREMENTS_REL)[1]
    scene_names = set(list_requirement_scene_names(req_body))
    changes = _parse_design_changes(body)
    for change in changes:
        change_type = change.fields.get("类型", "").strip()
        if change_type not in CHANGE_TYPES:
            errors.append(f"变化「{change.name}」类型无效")
        scene = change.fields.get("场景", "").strip()
        if scene not in scene_names:
            errors.append(f"变化「{change.name}」引用了未知场景")
        for field in ("行为", "不变量"):
            if not change.fields.get(field, "").strip():
                errors.append(f"变化「{change.name}」缺少{field}")
    return errors


@dataclass
class _SectionItem:
    name: str
    fields: dict[str, str]


def _parse_facts(body: str) -> list[_SectionItem]:
    return _parse_section_items(body, "## 事实", ("证据", "说明"))


def _parse_unknowns(body: str) -> list[_SectionItem]:
    return _parse_section_items(body, "## 未知", ("影响", "阻塞"))


def _parse_design_changes(body: str) -> list[_SectionItem]:
    return _parse_section_items(body, "## 变化", ("类型", "场景", "行为", "不变量"))


def _parse_section_items(body: str, section_title: str, fields: tuple[str, ...]) -> list[_SectionItem]:
    lines = body.splitlines()
    items: list[_SectionItem] = []
    in_section = False
    current: _SectionItem | None = None
    for line in lines:
        if line.strip() == section_title:
            in_section = True
            continue
        if line.startswith("## ") and in_section:
            break
        if not in_section:
            continue
        if line.startswith("### "):
            if current is not None:
                items.append(current)
            current = _SectionItem(name=line[4:].strip(), fields={})
            continue
        if current is None:
            continue
        for field in fields:
            if line.strip().startswith(f"- {field}：") or line.strip().startswith(f"- {field}:"):
                parts = re.split(r"[：:]", line.strip()[2:].strip(), maxsplit=1)
                if len(parts) == 2:
                    current.fields[field] = parts[1].strip()
    if current is not None:
        items.append(current)
    return items


def _unknown_section_text(body: str) -> str:
    lines = body.splitlines()
    capture = False
    chunks: list[str] = []
    for line in lines:
        if line.strip() == "## 未知":
            capture = True
            continue
        if line.startswith("## ") and capture:
            break
        if capture and not line.startswith("### "):
            chunks.append(line.strip())
    return "\n".join(chunk for chunk in chunks if chunk)


def _build_design_review_prompt(materials: list[str]) -> str:
    material_lines = "\n".join(f"- {item}" for item in materials)
    return (
        "你是设计评审角色。只读下列材料，允许查看的路径仅限材料列表中的需求总览、调查总览与设计总览。"
        "不要修改工程，不要读取或引用实施目录。\n\n"
        f"materials：\n{material_lines}\n\n"
        "请给出整体结论：pass、fail 或 unverified 之一，并说明理由。"
        "若存在更简单的替代方案，请明确指出。"
    )


def _load_context(project_root: Path, feature_id: str) -> tuple[Path, Path, dict[str, object]]:
    _validate_feature_id(feature_id)
    _validate_project(project_root)
    project_root = project_root.resolve()
    archive = archive_dir(project_root, feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")
    return project_root, archive, read_feature_meta(archive / "feature.json")


def _require_requirements_approved(archive: Path, feature_id: str, feature_meta: dict[str, object]) -> None:
    state = compute_requirements_approval_state(archive, feature_id, feature_meta)
    if state != "approved":
        raise DeliveryError(
            code="REQUIREMENTS_NOT_APPROVED",
            message=f"需求尚未批准或已失效: {state}",
            exit_code=1,
        )


def _require_investigation_not_blocked(archive: Path) -> None:
    _meta, body = read_managed_document(archive / INVESTIGATION_REL)
    if investigation_has_blocking_unknowns(body):
        raise DeliveryError(code="INVESTIGATION_BLOCKED", message="调查仍有阻塞未知", exit_code=1)


def _feature_json_with_updated_at(feature_meta: dict[str, object], now_fn: NowFn) -> str:
    meta = dict(feature_meta)
    meta["updatedAt"] = format_iso8601(now_fn())
    return json.dumps(meta, indent=2, ensure_ascii=False) + "\n"


def _atomic_write_files(writes: dict[Path, str]) -> None:
    temp_paths: dict[Path, Path] = {}
    try:
        for target, content in writes.items():
            temp_path = target.with_suffix(target.suffix + ".tmp")
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(content, encoding="utf-8", newline="\n")
            temp_paths[target] = temp_path
        for target, temp_path in temp_paths.items():
            os.replace(temp_path, target)
    except Exception:
        for temp_path in temp_paths.values():
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
        raise


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: val for key, val in value.items() if isinstance(key, str) and isinstance(val, str)}


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
