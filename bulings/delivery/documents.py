from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.frontmatter import render_frontmatter, split_frontmatter
from bulings.delivery.paths import (
    CONTENT_STATUSES,
    MANAGED_DOCUMENTS,
    archive_dir,
    document_id,
    rel_path_for_document,
    sort_document_ids,
    stage_for_document_id,
)
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.validation import validate_delivery, validate_dependency_graph

NowFn = Callable[[], datetime]

README_TITLES: dict[str, str] = {
    "01-requirements/README.md": "需求",
    "02-investigation/README.md": "调查",
    "03-design/README.md": "设计",
    "04-plan/README.md": "计划",
    "05-implementation/README.md": "实施",
    "06-validation/README.md": "验证",
}

TERMINOLOGY_BODY = "# 术语\n\n## 已确认术语\n\n## 候选术语\n\n"
PLACEHOLDER_BODY_SUFFIX = "\n\n待填写。\n"


@dataclass(frozen=True)
class ConfirmResult:
    status: str
    documents: list[str]


@dataclass(frozen=True)
class QueueEntry:
    document_id: str
    reason: str


@dataclass(frozen=True)
class AssertFreshResult:
    status: str


def initial_body_for(rel: str) -> str:
    if rel == "01-requirements/terminology.md":
        return TERMINOLOGY_BODY
    heading = README_TITLES[rel]
    return f"# {heading}{PLACEHOLDER_BODY_SUFFIX}"


def initial_frontmatter(feature_id: str, rel: str, body: str) -> dict[str, Any]:
    suffix = next(item[1] for item in MANAGED_DOCUMENTS if item[0] == rel)
    doc = document_id(feature_id, suffix)
    terminology_id = document_id(feature_id, "requirements.terminology")
    dependencies: list[str] = []
    dependency_versions: dict[str, str] = {}
    if suffix == "requirements.overview":
        dependencies = [terminology_id]
        dependency_versions = {terminology_id: "0.1.0"}
    fingerprint = content_fingerprint(body if body.startswith("\n") else "\n" + body)
    return {
        "id": doc,
        "contentStatus": "draft",
        "semanticVersion": "0.1.0",
        "fingerprint": fingerprint,
        "dependencies": dependencies,
        "dependencyVersions": dependency_versions,
        "relatedDocuments": [],
        "staleFromStatus": "draft",
    }


def render_managed_markdown(feature_id: str, rel: str) -> str:
    body = initial_body_for(rel)
    meta = initial_frontmatter(feature_id, rel, body)
    normalized_body = body if body.startswith("\n") else "\n" + body
    return render_frontmatter(meta, normalized_body)


def read_managed_document(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    return meta, body


def body_fingerprint(body: str) -> str:
    normalized = body if body.startswith("\n") else "\n" + body
    return content_fingerprint(normalized)


def bump_patch_version(version: str) -> str:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise DeliveryError(code="INVALID_VERSION", message=f"无法解析语义版本: {version}")
    major, minor, patch = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return f"{major}.{minor}.{patch + 1}"


def confirm_change(
    project_root: Path,
    feature_id: str,
    document_ids: list[str],
    semantic_change: bool,
    *,
    now: NowFn | None = None,
) -> ConfirmResult:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    _validate_feature_id(feature_id)
    if not document_ids:
        raise DeliveryError(code="MISSING_DOCUMENT", message="至少指定一个 --document-id", exit_code=2)

    archive = archive_dir(project_root.resolve(), feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")

    feature_path = archive / "feature.json"
    feature_meta = read_feature_meta(feature_path)
    lifecycle = feature_meta.get("lifecycle")
    if lifecycle in {"frozen", "pending_cleanup"}:
        raise DeliveryError(code="LIFECYCLE_FROZEN", message="交付项已冻结，无法确认变更", exit_code=1)

    loaded: dict[str, tuple[str, dict[str, Any], str, Path]] = {}
    unique_ids = list(dict.fromkeys(document_ids))
    for doc in unique_ids:
        rel = rel_path_for_document(feature_id, doc)
        if rel is None:
            raise DeliveryError(code="UNKNOWN_DOCUMENT", message=f"未知文档标识: {doc}", exit_code=1)
        path = archive / rel
        meta, body = read_managed_document(path)
        _validate_document_meta(meta, doc)
        deps = _string_list(meta.get("dependencies"))
        validate_dependency_graph(feature_id, doc, deps)
        loaded[doc] = (rel, meta, body, path)

    updates: dict[str, tuple[dict[str, Any], str]] = {}
    for doc, (_rel, meta, body, _path) in loaded.items():
        deps = _string_list(meta.get("dependencies"))
        current_fp = body_fingerprint(body)
        if meta.get("fingerprint") == current_fp and deps == _string_list(meta.get("dependencies")):
            continue
        new_meta = dict(meta)
        new_meta["fingerprint"] = current_fp
        if not semantic_change:
            if new_meta.get("contentStatus") == "stale":
                new_meta["contentStatus"] = new_meta.get("staleFromStatus", "draft")
            new_meta["dependencyVersions"] = _current_dependency_versions(archive, feature_id, deps)
        else:
            new_meta["semanticVersion"] = bump_patch_version(str(meta.get("semanticVersion", "0.1.0")))
        updates[doc] = (new_meta, body)

    if not updates:
        return ConfirmResult(status="unchanged", documents=[])

    stale_targets: set[str] = set()
    if semantic_change:
        for doc in updates:
            stale_targets.update(_direct_dependents(archive, feature_id, doc))

    for target in stale_targets:
        if target in updates:
            new_meta, body = updates[target]
            new_meta = dict(new_meta)
        else:
            rel = rel_path_for_document(feature_id, target)
            if rel is None:
                continue
            meta, body = read_managed_document(archive / rel)
            new_meta = dict(meta)
        if new_meta.get("contentStatus") != "stale":
            new_meta["staleFromStatus"] = new_meta.get("contentStatus", "draft")
            new_meta["contentStatus"] = "stale"
        updates[target] = (new_meta, body)

    pending_writes: dict[Path, str] = {}
    for doc, (new_meta, body) in updates.items():
        rel = rel_path_for_document(feature_id, doc)
        if rel is None:
            continue
        normalized_body = body if body.startswith("\n") else "\n" + body
        pending_writes[archive / rel] = render_frontmatter(new_meta, normalized_body)

    stamp = format_iso8601(now_fn())
    feature_meta = dict(feature_meta)
    feature_meta["updatedAt"] = stamp
    pending_writes[feature_path] = json.dumps(feature_meta, indent=2, ensure_ascii=False) + "\n"

    _atomic_write_files(pending_writes)
    return ConfirmResult(status="confirmed", documents=sorted(updates.keys()))


def refresh_queue(project_root: Path, feature_id: str) -> list[QueueEntry]:
    _validate_feature_id(feature_id)
    archive = archive_dir(project_root.resolve(), feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")
    feature_meta = read_feature_meta(archive / "feature.json")
    if feature_meta.get("lifecycle") == "frozen":
        return []

    entries: list[QueueEntry] = []
    for _rel, suffix, _stage in MANAGED_DOCUMENTS:
        doc = document_id(feature_id, suffix)
        path = archive / _rel
        meta, _body = read_managed_document(path)
        reasons: list[str] = []
        if meta.get("contentStatus") == "stale":
            reasons.append("stale")
        deps = _string_list(meta.get("dependencies"))
        dep_versions = _string_dict(meta.get("dependencyVersions"))
        for dep in deps:
            dep_meta = _read_document_meta(archive, feature_id, dep)
            if dep_versions.get(dep) != dep_meta.get("semanticVersion"):
                reasons.append("dependencyVersion")
                break
        if reasons:
            entries.append(QueueEntry(document_id=doc, reason=",".join(sorted(set(reasons)))))
    ordered_ids = sort_document_ids(feature_id, [entry.document_id for entry in entries])
    order_index = {doc: index for index, doc in enumerate(ordered_ids)}
    entries.sort(key=lambda item: order_index[item.document_id])
    return entries


def assert_fresh(project_root: Path, feature_id: str, document_ids: list[str]) -> AssertFreshResult:
    if not document_ids:
        raise DeliveryError(code="MISSING_DOCUMENT", message="至少指定一个 --document-id", exit_code=2)
    queue = {entry.document_id for entry in refresh_queue(project_root, feature_id)}
    stale = sort_document_ids(feature_id, [doc for doc in document_ids if doc in queue])
    if stale:
        raise DeliveryError(
            code="STALE_DOCUMENT",
            message="文档未通过新鲜度检查",
            exit_code=1,
            blockers=[Blocker(code="STALE_DOCUMENT", message="文档过期", path=doc) for doc in stale],
        )
    return AssertFreshResult(status="fresh")


def validate_delivery_errors(project_root: Path, feature_id: str) -> list[dict[str, str]]:
    archive = archive_dir(project_root.resolve(), feature_id)
    return [item.to_dict() for item in validate_delivery(archive, feature_id)]


def _direct_dependents(archive: Path, feature_id: str, changed_doc: str) -> list[str]:
    dependents: list[str] = []
    for _rel, suffix, _stage in MANAGED_DOCUMENTS:
        doc = document_id(feature_id, suffix)
        if doc == changed_doc:
            continue
        path = archive / _rel
        meta, _body = read_managed_document(path)
        if changed_doc in _string_list(meta.get("dependencies")):
            dependents.append(doc)
    return dependents


def _current_dependency_versions(archive: Path, feature_id: str, dependencies: list[str]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for dep in dependencies:
        dep_meta = _read_document_meta(archive, feature_id, dep)
        versions[dep] = str(dep_meta.get("semanticVersion", "0.1.0"))
    return versions


def _read_document_meta(archive: Path, feature_id: str, doc: str) -> dict[str, Any]:
    rel = rel_path_for_document(feature_id, doc)
    if rel is None:
        raise DeliveryError(code="UNKNOWN_DOCUMENT", message=f"未知文档标识: {doc}")
    meta, _body = read_managed_document(archive / rel)
    return meta


def _validate_document_meta(meta: dict[str, Any], expected_id: str) -> None:
    if meta.get("id") != expected_id:
        raise DeliveryError(code="INVALID_FRONTMATTER", message="文档标识与前置不一致", exit_code=1)
    status = meta.get("contentStatus")
    if status not in CONTENT_STATUSES:
        raise DeliveryError(code="INVALID_CONTENT_STATUS", message=f"非法 contentStatus: {status}", exit_code=1)


def _validate_feature_id(feature_id: str) -> None:
    if not is_valid_feature_id(feature_id):
        raise DeliveryError(
            code="INVALID_FEATURE_ID",
            message="feature-id 不合法",
            exit_code=2,
        )


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: val for key, val in value.items() if isinstance(key, str) and isinstance(val, str)}


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
