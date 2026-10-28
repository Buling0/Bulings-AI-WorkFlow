from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.lease_flow import load_task_package
from bulings.delivery.lease_store import delete_lease, read_lease, write_lease
from bulings.delivery.slice_state import set_slice_state
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.workspace import file_digest, has_in_scope_changes, inspect_lease_workspace

CHECKPOINTS = "05-implementation/checkpoints.jsonl"
REVIEWS = "05-implementation/reviews.jsonl"
CANDIDATES = "05-implementation/candidates"


def checkpoint_slice(
    project_root: Path,
    feature_id: str,
    execution_id: str,
    summary: str,
    validation_result: str,
    *,
    covered_validation: list[str] | None = None,
    now,
) -> str:
    _reject_circuit_open(project_root, feature_id, execution_id)
    lease = _require_lease(project_root, feature_id, execution_id, {"active"})
    inspect_lease_workspace(project_root, feature_id)
    text = summary.strip()
    if not text:
        raise DeliveryError(code="INVALID_SUMMARY", message="summary 不能为空", exit_code=2)
    if validation_result not in {"passed", "failed", "unverified"}:
        raise DeliveryError(code="INVALID_VALIDATION", message="validation-result 无效", exit_code=2)
    archive = project_root / ".bulings" / "deliveries" / feature_id
    path = archive / CHECKPOINTS
    entry = {
        "executionId": execution_id,
        "sliceId": lease.get("sliceId"),
        "summary": text,
        "validationResult": validation_result,
        "createdAt": format_iso8601(now()),
    }
    if covered_validation:
        entry["coveredValidation"] = covered_validation
    _attach_scope_digests(entry, project_root, lease)
    if path.is_file():
        last = _last_checkpoint(path)
        if (
            last
            and last.get("executionId") == execution_id
            and last.get("summary") == text
            and last.get("validationResult") == validation_result
            and _scope_digests_match(project_root, lease, last)
        ):
            return "unchanged"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return "recorded"


def submit_slice(project_root: Path, feature_id: str, execution_id: str, *, now) -> str:
    _reject_circuit_open(project_root, feature_id, execution_id)
    lease = _require_lease(project_root, feature_id, execution_id, {"active"})
    inspect_lease_workspace(project_root, feature_id)
    if not has_in_scope_changes(project_root, lease):
        raise DeliveryError(code="EMPTY_CANDIDATE", message="范围内无变化", exit_code=1)
    archive = project_root / ".bulings" / "deliveries" / feature_id
    cp = archive / CHECKPOINTS
    if not cp.is_file():
        raise DeliveryError(code="NO_CHECKPOINT", message="缺少检查点", exit_code=1)
    passed = [line for line in _read_jsonl(cp) if line.get("executionId") == execution_id and line.get("validationResult") == "passed"]
    if not passed:
        raise DeliveryError(code="NO_PASSED_CHECKPOINT", message="缺少通过的检查点", exit_code=1)
    last = passed[-1]
    package = load_task_package(project_root, feature_id, str(lease.get("sliceId")))
    covered = last.get("coveredValidation") or []
    for item in package.get("validation", []):
        if item not in covered and item not in last.get("summary", ""):
            raise DeliveryError(code="VALIDATION_NOT_COVERED", message=f"未覆盖验证: {item}", exit_code=1)
    candidate_id = _next_candidate_id(archive, str(lease.get("sliceId")))
    files = _candidate_files(project_root, lease)
    payload = {
        "candidateId": candidate_id,
        "sliceId": lease.get("sliceId"),
        "executionId": execution_id,
        "packageDigest": lease.get("packageDigest"),
        "planVersion": package.get("planVersion"),
        "planDigest": package.get("planDigest"),
        "files": files,
        "createdAt": format_iso8601(now()),
    }
    cand_dir = archive / CANDIDATES
    cand_dir.mkdir(parents=True, exist_ok=True)
    (cand_dir / f"{candidate_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    lease["status"] = "in_review"
    write_lease(project_root, feature_id, lease)
    set_slice_state(project_root, feature_id, str(lease.get("sliceId")), "in_review", candidate_id=candidate_id)
    return candidate_id


def review_prompt(project_root: Path, feature_id: str, candidate_id: str) -> dict[str, Any]:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    rel = f".bulings/deliveries/{feature_id}"
    materials = [
        f"{rel}/{CANDIDATES}/{candidate_id}.json",
        f"{rel}/05-implementation/packages/{_candidate_slice(archive, candidate_id)}.json",
        f"{rel}/01-requirements/README.md",
        f"{rel}/03-design/README.md",
        f"{rel}/04-plan/README.md",
    ]
    prompt = (
        "你是候选评审。只读材料列表中的文件，禁止修改文件，禁止阅读协调者对话。\n"
        "结论必须是 pass、fail 或 unverified 之一。\n"
        f"materials:\n" + "\n".join(f"- {m}" for m in materials)
    )
    return {"featureId": feature_id, "role": "candidate-review", "prompt": prompt, "materials": materials}


def review_slice(
    project_root: Path,
    feature_id: str,
    candidate_id: str,
    execution_id: str,
    decision: str,
    summary: str,
    *,
    now,
) -> str:
    if decision not in {"pass", "fail", "unverified"}:
        raise DeliveryError(code="INVALID_DECISION", message="decision 无效", exit_code=2)
    archive = project_root / ".bulings" / "deliveries" / feature_id
    cand_path = archive / CANDIDATES / f"{candidate_id}.json"
    candidate = json.loads(cand_path.read_text(encoding="utf-8"))
    if execution_id == candidate.get("executionId"):
        raise DeliveryError(code="REVIEW_NOT_INDEPENDENT", message="评审标识不能与实施相同", exit_code=1)
    lease = read_lease(project_root, feature_id)
    if lease is None or lease.get("status") != "in_review":
        raise DeliveryError(code="NO_REVIEW_LEASE", message="租约不在评审中", exit_code=1)
    current_files = _candidate_files(project_root, lease)
    if current_files != candidate.get("files"):
        raise DeliveryError(code="CANDIDATE_CHANGED", message="候选与当前工作区不一致", exit_code=1)
    record = {
        "candidateId": candidate_id,
        "executionId": execution_id,
        "decision": decision,
        "summary": summary.strip(),
        "createdAt": format_iso8601(now()),
    }
    with (archive / REVIEWS).open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
    slice_id = str(lease.get("sliceId"))
    if decision == "pass":
        delete_lease(project_root, feature_id)
        set_slice_state(project_root, feature_id, slice_id, "accepted", candidate_id=candidate_id)
    else:
        lease["status"] = "active"
        write_lease(project_root, feature_id, lease)
        set_slice_state(project_root, feature_id, slice_id, "changes_requested", candidate_id=candidate_id)
    return decision


def _candidate_files(project_root: Path, lease: dict[str, Any]) -> dict[str, str]:
    from bulings.delivery.lease_flow import expand_write_scope, load_task_package

    package = load_task_package(project_root, str(lease.get("featureId")), str(lease.get("sliceId")))
    files: dict[str, str] = {}
    for rel in expand_write_scope(project_root, package.get("writeScope", [])):
        path = project_root / rel
        if path.is_file():
            files[rel] = file_digest(path)
    return files


def _reject_circuit_open(project_root: Path, feature_id: str, execution_id: str) -> None:
    lease = read_lease(project_root, feature_id)
    if (
        lease is not None
        and lease.get("status") == "circuit_open"
        and lease.get("executionId") == execution_id
    ):
        raise DeliveryError(code="CIRCUIT_OPEN", message="熔断已打开", exit_code=1)


def _require_lease(project_root: Path, feature_id: str, execution_id: str, statuses: set[str]) -> dict[str, Any]:
    lease = read_lease(project_root, feature_id)
    if lease is None or lease.get("status") not in statuses:
        raise DeliveryError(code="NO_LEASE", message="租约状态不匹配", exit_code=1)
    if lease.get("executionId") != execution_id:
        raise DeliveryError(code="EXECUTION_MISMATCH", message="执行标识不匹配", exit_code=1)
    return lease


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            lines.append(json.loads(line))
    return lines


def _last_checkpoint(path: Path) -> dict[str, Any] | None:
    items = _read_jsonl(path)
    return items[-1] if items else None


def _next_candidate_id(archive: Path, slice_id: str) -> str:
    cand_dir = archive / CANDIDATES
    index = 1
    if cand_dir.is_dir():
        index = len(list(cand_dir.glob(f"c-{slice_id}-*.json"))) + 1
    return f"c-{slice_id}-{index}"


def _candidate_slice(archive: Path, candidate_id: str) -> str:
    data = json.loads((archive / CANDIDATES / f"{candidate_id}.json").read_text(encoding="utf-8"))
    return str(data.get("sliceId", ""))


def _scope_digests_match(project_root: Path, lease: dict[str, Any], last: dict[str, Any]) -> bool:
    current = _candidate_files(project_root, lease)
    stored = last.get("scopeDigests")
    if isinstance(stored, dict):
        return stored == current
    return True


def _attach_scope_digests(entry: dict[str, Any], project_root: Path, lease: dict[str, Any]) -> None:
    entry["scopeDigests"] = _candidate_files(project_root, lease)
