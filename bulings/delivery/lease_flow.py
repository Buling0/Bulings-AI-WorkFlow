from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from bulings.config import load_workflow_config
from bulings.delivery.archive import archive_dir
from bulings.delivery.lease_store import delete_lease, find_global_lease, read_lease, write_lease
from bulings.delivery.design_flow import design_ready
from bulings.delivery.documents import assert_fresh, read_managed_document
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.git_util import git_hash_file, git_head, git_porcelain, is_git_repo
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import compute_requirements_approval_state
from bulings.delivery.slice_plan import (
    PLAN_REL,
    compute_slice_eligibility,
    plan_digest,
    read_slice_plan_status,
)
from bulings.delivery.time_util import format_iso8601
from bulings.install import is_unity_project

PACKAGE_DIR = "05-implementation/packages"
LEASE_NAME = "lease.json"
EXEC_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

def package_path(archive: Path, slice_id: str) -> Path:
    return archive / PACKAGE_DIR / f"{slice_id}.json"


def prepare_task_package(project_root: Path, feature_id: str, slice_id: str) -> dict[str, str]:
    _validate_ids(feature_id, slice_id)
    archive = _archive(project_root, feature_id)
    path = package_path(archive, slice_id)
    if path.is_file():
        return {"status": "unchanged", "path": _rel_package(feature_id, slice_id)}
    approved = _approved_plan(archive)
    payload = {
        "schema": 1,
        "featureId": feature_id,
        "sliceId": slice_id,
        "planVersion": approved.get("version"),
        "planDigest": approved.get("digest"),
        "writeScope": [],
        "acceptance": ["待填写验收项"],
        "validation": ["待填写验证命令"],
        "rollback": "恢复本切片启动时的范围内文件",
        "scenarios": [],
        "circuitRules": [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return {"status": "created", "path": _rel_package(feature_id, slice_id)}


def check_task_package(project_root: Path, feature_id: str, slice_id: str) -> str:
    _validate_ids(feature_id, slice_id)
    digest, blockers = _task_package_check(project_root, feature_id, slice_id, include_lease_check=True)
    if blockers:
        raise DeliveryError(code="INVALID_PACKAGE", message="任务包检查失败", exit_code=1, blockers=blockers)
    return digest


def _task_package_check(
    project_root: Path,
    feature_id: str,
    slice_id: str,
    *,
    include_lease_check: bool,
    include_eligibility: bool = True,
) -> tuple[str, list[Blocker]]:
    archive = _archive(project_root, feature_id)
    package = load_task_package(project_root, feature_id, slice_id)
    blockers = _validate_package(
        project_root, archive, feature_id, slice_id, package, include_eligibility=include_eligibility
    )
    if include_lease_check and find_global_lease(project_root):
        blockers.append(Blocker(code="LEASE_HELD", message="已有活动租约"))
    return package_digest(package), blockers


def start_slice(
    project_root: Path,
    feature_id: str,
    slice_id: str,
    execution_id: str,
    *,
    now,
) -> str:
    _validate_ids(feature_id, slice_id)
    if not EXEC_ID.fullmatch(execution_id):
        raise DeliveryError(code="INVALID_EXECUTION_ID", message="execution-id 不合法", exit_code=2)
    project_root = project_root.resolve()
    if not is_git_repo(project_root):
        raise DeliveryError(code="GIT_REQUIRED", message="工程必须是 Git 工作区", exit_code=1)
    archive = _archive(project_root, feature_id)
    lease_path = archive / LEASE_NAME
    digest_loose, blockers_loose = _task_package_check(
        project_root, feature_id, slice_id, include_lease_check=False, include_eligibility=False
    )
    if blockers_loose:
        raise DeliveryError(code="INVALID_PACKAGE", message="任务包检查失败", exit_code=1, blockers=blockers_loose)
    if lease_path.is_file():
        existing = json.loads(lease_path.read_text(encoding="utf-8"))
        if (
            existing.get("executionId") == execution_id
            and existing.get("packageDigest") == digest_loose
            and existing.get("sliceId") == slice_id
            and _baseline_files_match(project_root, existing)
        ):
            return "unchanged"
        raise DeliveryError(code="LEASE_CONFLICT", message="租约冲突", exit_code=1)
    digest, blockers = _task_package_check(
        project_root, feature_id, slice_id, include_lease_check=False, include_eligibility=True
    )
    if blockers:
        raise DeliveryError(code="INVALID_PACKAGE", message="任务包检查失败", exit_code=1, blockers=blockers)
    if find_global_lease(project_root):
        raise DeliveryError(code="LEASE_HELD", message="已有活动租约", exit_code=1)
    from bulings.delivery.slice_state import get_slice_state

    if get_slice_state(project_root, feature_id, slice_id) == "released":
        raise DeliveryError(code="SLICE_RELEASED", message="切片已 release", exit_code=1)
    package = load_task_package(project_root, feature_id, slice_id)
    baseline = _build_baseline(project_root, archive, feature_id, execution_id, package)
    lease = {
        "schema": 1,
        "featureId": feature_id,
        "sliceId": slice_id,
        "executionId": execution_id,
        "packageDigest": digest,
        "status": "active",
        "startedAt": format_iso8601(now()),
        "contractVersion": 1,
        "baseline": baseline,
    }
    write_lease(project_root, feature_id, lease)
    from bulings.delivery.slice_state import set_slice_state

    set_slice_state(project_root, feature_id, slice_id, "active")
    return "started"


def load_task_package(project_root: Path, feature_id: str, slice_id: str) -> dict[str, Any]:
    path = package_path(_archive(project_root, feature_id), slice_id)
    if not path.is_file():
        raise DeliveryError(code="MISSING_PACKAGE", message="缺少任务包", exit_code=1)
    return json.loads(path.read_text(encoding="utf-8"))


def package_digest(package: dict[str, Any]) -> str:
    normalized = normalize_task_package(package)
    text = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return content_fingerprint(text)


def normalize_task_package(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "acceptance": list(package.get("acceptance") or []),
        "circuitRules": sorted(set(str(x) for x in package.get("circuitRules") or [])),
        "featureId": package.get("featureId"),
        "planDigest": package.get("planDigest"),
        "planVersion": package.get("planVersion"),
        "rollback": package.get("rollback"),
        "schema": package.get("schema"),
        "scenarios": sorted(set(str(x) for x in package.get("scenarios") or [])),
        "sliceId": package.get("sliceId"),
        "validation": list(package.get("validation") or []),
        "writeScope": sorted(set(str(x) for x in package.get("writeScope") or [])),
    }


def expand_write_scope(project_root: Path, scope: list[str]) -> set[str]:
    files: set[str] = set()
    for item in scope:
        rel = item.replace("\\", "/")
        path = project_root / rel
        if rel.endswith("/"):
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        files.add(child.relative_to(project_root).as_posix())
        elif path.is_file():
            files.add(rel)
    return files


def path_in_scope(rel: str, scope: list[str]) -> bool:
    rel = rel.replace("\\", "/")
    for item in scope:
        s = item.replace("\\", "/")
        if s.endswith("/"):
            if rel.startswith(s):
                return True
        elif rel == s:
            return True
    return False


def _validate_package(
    project_root: Path,
    archive: Path,
    feature_id: str,
    slice_id: str,
    package: dict[str, Any],
    *,
    include_eligibility: bool = True,
) -> list[Blocker]:
    blockers: list[Blocker] = []
    approved = _approved_plan(archive)
    if package.get("planVersion") != approved.get("version") or package.get("planDigest") != approved.get("digest"):
        blockers.append(Blocker(code="PLAN_STALE", message="任务包与批准方案不一致"))
    if include_eligibility:
        from bulings.delivery.slice_state import load_slice_states

        approved_plan = json.loads((archive / "04-plan/slice-plan.approved.json").read_text(encoding="utf-8"))
        raw_states = load_slice_states(project_root, feature_id)
        states = {sid: data.get("state", "pending") for sid, data in raw_states.items()}
        eligibility = compute_slice_eligibility(approved_plan, states)
        if eligibility.get(slice_id) != "ready":
            blockers.append(Blocker(code="SLICE_NOT_READY", message="切片不可启动"))
    meta = read_feature_meta(archive / "feature.json")
    if compute_requirements_approval_state(archive, feature_id, meta) != "approved":
        blockers.append(Blocker(code="REQUIREMENTS", message="需求未批准"))
    try:
        design_ready(project_root, feature_id)
    except DeliveryError as error:
        blockers.append(Blocker(code="DESIGN_NOT_READY", message=error.message))
    try:
        assert_fresh(project_root, feature_id, [document_id(feature_id, "plan.overview")])
    except DeliveryError:
        blockers.append(Blocker(code="STALE", message="计划未新鲜"))
    scope = package.get("writeScope")
    if not isinstance(scope, list) or len(scope) == 0:
        blockers.append(Blocker(code="INVALID_SCOPE", message="writeScope 为空"))
    else:
        blockers.extend(_scope_errors(project_root, scope))
    for field in ("acceptance", "validation"):
        values = package.get(field)
        if not isinstance(values, list) or not all(isinstance(v, str) and v.strip() for v in values):
            blockers.append(Blocker(code="INVALID_PACKAGE", message=f"{field} 无效"))
    profile = meta.get("profile", "delivery")
    if profile == "ui":
        from bulings.delivery.ui_flow import ui_start_checks

        blockers.extend(ui_start_checks(project_root, feature_id, package))
    return blockers


def _scope_errors(project_root: Path, scope: list[str]) -> list[Blocker]:
    errors: list[Blocker] = []
    protected = load_workflow_config(project_root).project.protected_paths
    for item in scope:
        if not isinstance(item, str):
            errors.append(Blocker(code="INVALID_SCOPE", message="路径必须是字符串"))
            continue
        rel = item.replace("\\", "/")
        if not _valid_scope_entry(rel):
            errors.append(Blocker(code="INVALID_SCOPE", message=f"非法路径: {rel}", path=rel))
            continue
        if rel.startswith(".bulings/") or "/.bulings/" in rel:
            errors.append(Blocker(code="INVALID_SCOPE", message="不能包含 .bulings", path=rel))
        for prot in protected:
            p = prot.replace("\\", "/")
            if rel == p or rel.startswith(p.rstrip("/") + "/"):
                errors.append(Blocker(code="INVALID_SCOPE", message=f"与保护路径冲突: {p}", path=rel))
    return errors


def _valid_scope_entry(rel: str) -> bool:
    if not rel or rel.startswith("/") or ":" in rel or ".." in rel or "*" in rel or "?" in rel:
        return False
    if rel.endswith("/"):
        return True
    return not rel.endswith("/")


def _build_baseline(
    project_root: Path,
    archive: Path,
    feature_id: str,
    execution_id: str,
    package: dict[str, Any],
) -> dict[str, Any]:
    scope = package.get("writeScope", [])
    files_meta: dict[str, Any] = {}
    baseline_root = archive / "baselines" / execution_id
    for rel in sorted(expand_write_scope(project_root, scope) | set(str(x).replace("\\", "/") for x in scope if not str(x).endswith("/"))):
        if rel.endswith("/"):
            continue
        path = project_root / rel
        entry: dict[str, Any] = {"existed": path.is_file()}
        if path.is_file():
            from bulings.delivery.workspace import file_digest

            digest = file_digest(path)
            entry["sha256"] = digest
            if rel.endswith(".meta"):
                from bulings.delivery.workspace import read_meta_guid

                entry["guid"] = read_meta_guid(path)
            dest = baseline_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            entry["bytesPath"] = f"baselines/{execution_id}/{rel}"
        files_meta[rel] = entry
    outside: dict[str, str] = {}
    scoped = expand_write_scope(project_root, scope)
    for rel, _st in git_porcelain(project_root).items():
        if rel in scoped:
            continue
        path = project_root / rel
        if path.is_file():
            outside[rel] = f"sha256:{git_hash_file(path)}"
    return {"gitHead": git_head(project_root), "files": files_meta, "outside": outside}


def _baseline_files_match(project_root: Path, lease: dict[str, Any]) -> bool:
    baseline = lease.get("baseline")
    if not isinstance(baseline, dict):
        return False
    files = baseline.get("files")
    if not isinstance(files, dict):
        return False
    for rel, meta in files.items():
        if not isinstance(meta, dict) or not meta.get("existed"):
            continue
        path = project_root / str(rel)
        if not path.is_file():
            return False
        from bulings.delivery.workspace import file_digest

        if file_digest(path) != meta.get("sha256"):
            return False
    return True


def _approved_plan(archive: Path) -> dict[str, Any]:
    path = archive / "04-plan/slice-plan.approved.json"
    if not path.is_file():
        raise DeliveryError(code="NO_APPROVED_PLAN", message="没有批准的切片方案", exit_code=1)
    return json.loads(path.read_text(encoding="utf-8"))


def _rel_package(feature_id: str, slice_id: str) -> str:
    return f".bulings/deliveries/{feature_id}/{PACKAGE_DIR}/{slice_id}.json"


def _archive(project_root: Path, feature_id: str) -> Path:
    if not is_valid_feature_id(feature_id):
        raise DeliveryError(code="INVALID_FEATURE_ID", message="feature-id 不合法", exit_code=2)
    if not is_unity_project(project_root):
        raise DeliveryError(code="NOT_UNITY_PROJECT", message="不是 Unity 工程", exit_code=1)
    archive = archive_dir(project_root.resolve(), feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message="找不到交付项", exit_code=1)
    return archive


def _validate_ids(feature_id: str, slice_id: str) -> None:
    if not is_valid_feature_id(feature_id) or not is_valid_feature_id(slice_id):
        raise DeliveryError(code="INVALID_ID", message="标识不合法", exit_code=2)


# 兼容外部导入
from bulings.delivery.lease_store import delete_lease, find_global_lease, read_lease  # noqa: E402
