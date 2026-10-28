from __future__ import annotations

import json
import shutil
from pathlib import Path

from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.lease_flow import load_task_package, package_digest
from bulings.delivery.lease_store import delete_lease, read_lease, write_lease
from bulings.delivery.slice_state import set_slice_state
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.workspace import file_digest

CIRCUIT_RULES = frozenset(
    {
        "acceptance-changed",
        "scope-required",
        "dependency-lost",
        "shared-data",
        "invariant-broken",
        "not-independent",
        "rollback-lost",
        "package-rule",
    }
)
CIRCUITS = "05-implementation/circuits.jsonl"


def open_circuit(
    project_root: Path,
    feature_id: str,
    execution_id: str,
    rule: str,
    summary: str,
    *,
    now,
) -> None:
    if rule not in CIRCUIT_RULES:
        raise DeliveryError(code="INVALID_RULE", message="规则标识无效", exit_code=2)
    lease = _require_active(project_root, feature_id, execution_id)
    text = summary.strip()
    if not text:
        raise DeliveryError(code="INVALID_SUMMARY", message="summary 不能为空", exit_code=2)
    if rule == "package-rule":
        package = load_task_package(project_root, feature_id, str(lease.get("sliceId")))
        rules = package.get("circuitRules") or []
        if not any(text.startswith(str(item)) for item in rules):
            raise DeliveryError(code="INVALID_RULE", message="summary 未匹配 circuitRules", exit_code=1)
    archive = project_root / ".bulings/deliveries" / feature_id
    lease["status"] = "circuit_open"
    write_lease(project_root, feature_id, lease)
    entry = {"executionId": execution_id, "rule": rule, "summary": text, "createdAt": format_iso8601(now())}
    with (archive / CIRCUITS).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def resolve_slice(project_root: Path, feature_id: str, action: str, *, execution_id: str | None = None) -> str:
    lease = read_lease(project_root, feature_id)
    if lease is None or lease.get("status") != "circuit_open":
        raise DeliveryError(code="NOT_CIRCUIT", message="不在熔断状态", exit_code=1)
    archive = project_root / ".bulings/deliveries" / feature_id
    if action == "retry":
        if not execution_id:
            raise DeliveryError(code="MISSING_EXECUTION_ID", message="retry 需要新 execution-id", exit_code=2)
        if execution_id == lease.get("executionId"):
            raise DeliveryError(code="INVALID_EXECUTION_ID", message="需要不同的 execution-id", exit_code=2)
        lease["status"] = "active"
        lease["executionId"] = execution_id
        write_lease(project_root, feature_id, lease)
        return "retry"
    if action == "release":
        dirty = _baseline_dirty(project_root, lease)
        if dirty:
            raise DeliveryError(
                code="BASELINE_DIRTY",
                message="范围内与基线不一致",
                exit_code=1,
                blockers=[Blocker(code="BASELINE_DIRTY", message="与基线不一致", path=p) for p in dirty],
            )
        delete_lease(project_root, feature_id)
        set_slice_state(project_root, feature_id, str(lease.get("sliceId")), "released")
        return "released"
    raise DeliveryError(code="INVALID_ACTION", message="action 无效", exit_code=2)


def interrupt_slice(project_root: Path, feature_id: str, execution_id: str) -> str:
    lease = read_lease(project_root, feature_id)
    if lease is None:
        if _restored_to_baseline(project_root, feature_id, execution_id):
            return "unchanged"
        raise DeliveryError(code="NO_LEASE", message="没有租约", exit_code=1)
    if lease.get("status") != "active" or lease.get("executionId") != execution_id:
        raise DeliveryError(code="INVALID_LEASE", message="租约状态不允许中断", exit_code=1)
    _restore_baseline_bytes(project_root, feature_id, lease)
    delete_lease(project_root, feature_id)
    set_slice_state(project_root, feature_id, str(lease.get("sliceId")), "interrupted")
    return "interrupted"


def amend_scope(
    project_root: Path,
    feature_id: str,
    execution_id: str,
    paths: list[str],
    reason: str,
    authorization: str,
    next_execution_id: str,
    *,
    now,
) -> None:
    lease = read_lease(project_root, feature_id)
    if lease is None or lease.get("status") != "circuit_open":
        raise DeliveryError(code="NOT_CIRCUIT", message="需要 circuit_open", exit_code=1)
    from bulings.delivery.workspace import workspace_violations

    violations = {b.path for b in workspace_violations(project_root.resolve(), lease) if b.path}
    archive = project_root / ".bulings/deliveries" / feature_id
    package = load_task_package(project_root, feature_id, str(lease.get("sliceId")))
    for rel in paths:
        rel = rel.replace("\\", "/")
        if rel.endswith("/"):
            raise DeliveryError(code="INVALID_PATH", message="不能补登记目录", exit_code=2)
        if rel not in violations:
            raise DeliveryError(code="NOT_OUT_OF_SCOPE", message=f"路径不是当前越界: {rel}", exit_code=1)
        if rel not in package.get("writeScope", []):
            package.setdefault("writeScope", []).append(rel)
    if not reason.strip() or not authorization.strip():
        raise DeliveryError(code="INVALID_ARGS", message="reason 与 authorization 必填", exit_code=2)
    pkg_path = archive / "05-implementation/packages" / f"{lease.get('sliceId')}.json"
    pkg_path.write_text(json.dumps(package, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    lease["status"] = "active"
    lease["executionId"] = next_execution_id
    lease["contractVersion"] = int(lease.get("contractVersion", 1)) + 1
    lease["amendedPackageDigest"] = package_digest(package)
    write_lease(project_root, feature_id, lease)


def _restore_baseline_bytes(project_root: Path, feature_id: str, lease: dict) -> None:
    archive = project_root / ".bulings/deliveries" / feature_id
    baseline = lease.get("baseline", {})
    files = baseline.get("files", {})
    for rel, meta in files.items():
        if not isinstance(meta, dict):
            continue
        path = project_root / str(rel)
        if meta.get("existed"):
            src = archive / str(meta.get("bytesPath", ""))
            if src.is_file():
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, path)
        elif path.is_file():
            path.unlink()


def _baseline_dirty(project_root: Path, lease: dict) -> list[str]:
    dirty: list[str] = []
    files = lease.get("baseline", {}).get("files", {})
    for rel, meta in files.items():
        if not isinstance(meta, dict):
            continue
        path = project_root / str(rel)
        if meta.get("existed"):
            if not path.is_file() or file_digest(path) != str(meta.get("sha256", "")):
                dirty.append(str(rel))
        elif path.is_file():
            dirty.append(str(rel))
    return dirty


def _restored_to_baseline(project_root: Path, feature_id: str, execution_id: str) -> bool:
    return False


def _require_active(project_root: Path, feature_id: str, execution_id: str) -> dict:
    lease = read_lease(project_root, feature_id)
    if lease is None or lease.get("status") != "active" or lease.get("executionId") != execution_id:
        raise DeliveryError(code="NO_LEASE", message="需要 active 租约", exit_code=1)
    return lease
