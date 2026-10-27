from __future__ import annotations

import json
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.paths import ARCHIVE_RELATIVE_PATHS, archive_dir, archive_rel_path, deliveries_root
from bulings.delivery.documents import render_managed_markdown
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.design_flow import compute_architecture_approval_state
from bulings.delivery.slice_plan import compute_slice_eligibility, read_slice_plan_status
from bulings.delivery.requirements_flow import compute_requirements_approval_state
from bulings.delivery.validation import validate_delivery
from bulings.install import is_unity_project

NowFn = Callable[[], datetime]

@dataclass(frozen=True)
class InitResult:
    status: str
    feature_id: str
    archive: str


@dataclass(frozen=True)
class DeliverySummary:
    feature_id: str
    title: str
    lifecycle: str
    updated_at: str


@dataclass(frozen=True)
class StatusDetail:
    feature_id: str
    title: str
    profile: str
    lifecycle: str
    archive: str
    updated_at: str
    document_errors: list[dict[str, str]]
    approval_state: dict[str, str]
    slice_plan: dict[str, object] | None
    slice_eligibility: dict[str, str]


def default_now() -> datetime:
    return datetime.now(timezone.utc)


def init_delivery(
    project_root: Path,
    feature_id: str,
    title: str,
    *,
    now: NowFn | None = None,
) -> InitResult:
    now_fn = now or default_now
    project_root = project_root.resolve()
    _validate_project(project_root)
    _validate_feature_id(feature_id)
    normalized_title = _validate_title(title)

    destination = archive_dir(project_root, feature_id)
    if destination.exists():
        blockers = _collect_integrity_blockers(destination, feature_id)
        if blockers:
            raise DeliveryError(
                code="ARCHIVE_INVALID",
                message="交付档案不完整或无效，无法初始化",
                blockers=blockers,
            )
        return InitResult(status="unchanged", feature_id=feature_id, archive=archive_rel_path(feature_id))

    stamp = format_iso8601(now_fn())
    temp_parent = deliveries_root(project_root)
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_parent / f".{feature_id}.tmp-{secrets.token_hex(8)}"
    try:
        temp_dir.mkdir(parents=True, exist_ok=False)
        _write_new_archive(temp_dir, feature_id, normalized_title, stamp)
    except DeliveryError:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise

    try:
        temp_dir.rename(destination)
    except Exception as error:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise DeliveryError(code="INIT_FAILED", message=str(error)) from error

    return InitResult(status="created", feature_id=feature_id, archive=archive_rel_path(feature_id))


def list_deliveries(project_root: Path) -> tuple[list[DeliverySummary], list[str]]:
    project_root = project_root.resolve()
    root = deliveries_root(project_root)
    if not root.is_dir():
        return [], []

    deliveries: list[DeliverySummary] = []
    invalid: list[str] = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        feature_id = entry.name
        blockers = _collect_integrity_blockers(entry, feature_id)
        if blockers:
            invalid.append(feature_id)
            continue
        meta = read_feature_meta(entry / "feature.json")
        deliveries.append(
            DeliverySummary(
                feature_id=meta["featureId"],
                title=meta["title"],
                lifecycle=meta["lifecycle"],
                updated_at=meta["updatedAt"],
            )
        )
    return deliveries, invalid


def delivery_status(project_root: Path, feature_id: str) -> StatusDetail:
    project_root = project_root.resolve()
    _validate_feature_id(feature_id)
    destination = archive_dir(project_root, feature_id)
    if not destination.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")
    blockers = _collect_integrity_blockers(destination, feature_id)
    if blockers:
        raise DeliveryError(
            code="ARCHIVE_INVALID",
            message="交付档案不完整或无效",
            blockers=blockers,
        )
    meta = read_feature_meta(destination / "feature.json")
    doc_errors = [item.to_dict() for item in validate_delivery(destination, feature_id)]
    req_state = compute_requirements_approval_state(destination, feature_id, meta)
    arch_state = compute_architecture_approval_state(destination, feature_id, meta)
    slice_plan = read_slice_plan_status(destination)
    slice_eligibility: dict[str, str] = {}
    if slice_plan is not None and (approved_path := destination / "04-plan" / "slice-plan.approved.json").is_file():
        approved_data = json.loads(approved_path.read_text(encoding="utf-8"))
        slice_eligibility = compute_slice_eligibility(approved_data)
    return StatusDetail(
        feature_id=meta["featureId"],
        title=meta["title"],
        profile=meta["profile"],
        lifecycle=meta["lifecycle"],
        archive=archive_rel_path(feature_id),
        updated_at=meta["updatedAt"],
        document_errors=doc_errors,
        approval_state={"requirements": req_state, "architecture": arch_state},
        slice_plan=slice_plan,
        slice_eligibility=slice_eligibility,
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
        raise DeliveryError(
            code="INVALID_FEATURE_ID",
            message="feature-id 只允许小写英文、数字和连字符，长度 1 到 64，且不能以连字符开头或结尾",
            exit_code=2,
        )


def _validate_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise DeliveryError(code="INVALID_TITLE", message="title 去首尾空白后不能为空", exit_code=2)
    return normalized


def _write_new_archive(temp_dir: Path, feature_id: str, title: str, stamp: str) -> None:
    for rel in ARCHIVE_RELATIVE_PATHS:
        path = temp_dir / Path(rel)
        if _is_symlink(path):
            raise DeliveryError(code="SYMLINK", message=f"路径不能是符号链接: {rel}")
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "feature.json":
            payload = _feature_json_payload(feature_id, title, stamp)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        elif rel.endswith(".md"):
            path.write_text(render_managed_markdown(feature_id, rel), encoding="utf-8", newline="\n")
        else:
            raise DeliveryError(code="INTERNAL", message=f"未处理的档案路径: {rel}")


def _feature_json_payload(feature_id: str, title: str, stamp: str) -> dict[str, Any]:
    return {
        "schema": 1,
        "featureId": feature_id,
        "title": title,
        "profile": "delivery",
        "lifecycle": "draft",
        "createdAt": stamp,
        "updatedAt": stamp,
        "frozenAt": None,
        "retentionDays": 30,
        "validation": {
            "conclusion": "pending",
            "unverifiedBoundaries": "pending",
            "residualRisks": "pending",
        },
    }


def _collect_integrity_blockers(archive_path: Path, expected_feature_id: str) -> list[Blocker]:
    blockers: list[Blocker] = []
    for rel in ARCHIVE_RELATIVE_PATHS:
        path = archive_path / rel
        rel_posix = rel.replace("\\", "/")
        if _is_symlink(path):
            blockers.append(
                Blocker(code="SYMLINK", message="路径不能是符号链接", path=rel_posix),
            )
            continue
        if not path.is_file():
            blockers.append(
                Blocker(code="MISSING_FILE", message="缺少文件", path=rel_posix),
            )

    feature_path = archive_path / "feature.json"
    if feature_path.is_file() and not _is_symlink(feature_path):
        try:
            meta = read_feature_meta(feature_path)
        except DeliveryError as error:
            blockers.append(Blocker(code=error.code, message=error.message, path="feature.json"))
            return blockers
        if meta.get("schema") != 1:
            blockers.append(
                Blocker(code="INVALID_SCHEMA", message="schema 必须为 1", path="feature.json"),
            )
        if meta.get("featureId") != expected_feature_id:
            blockers.append(
                Blocker(
                    code="FEATURE_ID_MISMATCH",
                    message="featureId 与目录名不一致",
                    path="feature.json",
                ),
            )
        if meta.get("profile") != "delivery":
            blockers.append(
                Blocker(code="INVALID_PROFILE", message="profile 必须为 delivery", path="feature.json"),
            )
    return blockers


def _is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return False
