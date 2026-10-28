from __future__ import annotations

import re
from pathlib import Path

from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.lease_flow import expand_write_scope, path_in_scope
from bulings.delivery.lease_store import read_lease

META_GUID = re.compile(r"^guid:\s*(\S+)", re.MULTILINE)


def inspect_lease_workspace(project_root: Path, feature_id: str) -> None:
    project_root = project_root.resolve()
    lease = read_lease(project_root, feature_id)
    if lease is None:
        raise DeliveryError(code="NO_LEASE", message="没有活动租约", exit_code=1)
    blockers = workspace_violations(project_root, lease)
    if blockers:
        raise DeliveryError(
            code="WORKSPACE_SCOPE_VIOLATION",
            message="工作区越界",
            exit_code=1,
            blockers=blockers,
        )


def workspace_violations(project_root: Path, lease: dict[str, object]) -> list[Blocker]:
    blockers: list[Blocker] = []
    baseline = lease.get("baseline")
    if not isinstance(baseline, dict):
        return [Blocker(code="INVALID_LEASE", message="租约缺少 baseline")]
    files = baseline.get("files")
    outside = baseline.get("outside")
    if not isinstance(files, dict):
        files = {}
    if not isinstance(outside, dict):
        outside = {}

    package = _load_package_from_lease(project_root, lease)
    scope = expand_write_scope(project_root, package.get("writeScope", []))

    for rel, meta in files.items():
        if not isinstance(meta, dict):
            continue
        rel_posix = str(rel).replace("\\", "/")
        path = project_root / rel_posix
        existed = bool(meta.get("existed"))
        if existed:
            if not path.is_file():
                blockers.append(Blocker(code="SCOPE", message="范围内文件缺失", path=rel_posix))
                continue
            current = file_digest(path)
            stored = str(meta.get("sha256", ""))
            if stored and current != stored:
                if rel_posix.endswith(".meta"):
                    old_guid = meta.get("guid")
                    new_guid = read_meta_guid(path)
                    if old_guid and new_guid and old_guid != new_guid:
                        blockers.append(
                            Blocker(code="META_GUID_CHANGED", message="meta guid 已变化", path=rel_posix)
                        )
        else:
            if path.is_file() and rel_posix not in scope:
                blockers.append(Blocker(code="SCOPE", message="范围内不应存在的文件", path=rel_posix))

    for rel in scope:
        path = project_root / rel
        if path.is_file() and rel not in files:
            blockers.append(Blocker(code="SCOPE", message="范围内未授权的新文件", path=rel))

    for rel, digest in outside.items():
        if not isinstance(rel, str) or not isinstance(digest, str):
            continue
        path = project_root / rel
        if not path.is_file():
            blockers.append(Blocker(code="SCOPE", message="范围外文件被删除", path=rel))
            continue
        if file_digest(path) != digest:
            blockers.append(Blocker(code="SCOPE", message="范围外文件被修改", path=rel))

    from bulings.delivery.git_util import git_porcelain

    for rel, _status in git_porcelain(project_root).items():
        if rel in scope or rel in files:
            continue
        if rel in outside:
            continue
        path = project_root / rel
        if path.is_file():
            blockers.append(Blocker(code="SCOPE", message="出现新的范围外变更", path=rel))
    return blockers


def file_digest(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def read_meta_guid(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = META_GUID.search(text)
    return match.group(1) if match else None


def has_in_scope_changes(project_root: Path, lease: dict[str, object]) -> bool:
    baseline = lease.get("baseline")
    if not isinstance(baseline, dict):
        return False
    files = baseline.get("files")
    if not isinstance(files, dict):
        return False
    for rel, meta in files.items():
        if not isinstance(meta, dict):
            continue
        path = project_root / str(rel).replace("\\", "/")
        existed = bool(meta.get("existed"))
        if existed and path.is_file():
            if file_digest(path) != str(meta.get("sha256", "")):
                return True
        if not existed and path.is_file():
            return True
    package = _load_package_from_lease(project_root, lease)
    for rel in expand_write_scope(project_root, package.get("writeScope", [])):
        if rel not in files and (project_root / rel).is_file():
            return True
    return False


def _load_package_from_lease(project_root: Path, lease: dict[str, object]) -> dict[str, object]:
    from bulings.delivery.lease_flow import load_task_package

    feature_id = str(lease.get("featureId", ""))
    slice_id = str(lease.get("sliceId", ""))
    return load_task_package(project_root, feature_id, slice_id)
