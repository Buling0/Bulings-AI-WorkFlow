from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bulings.delivery.lease_store import find_global_lease, read_lease
from bulings.delivery.slice_plan import compute_slice_eligibility
from bulings.delivery.slice_state import load_slice_states


def lease_summary(project_root: Path, feature_id: str) -> dict[str, str] | None:
    lease = read_lease(project_root, feature_id)
    if lease is None:
        return None
    return {
        "sliceId": str(lease.get("sliceId", "")),
        "executionId": str(lease.get("executionId", "")),
        "status": str(lease.get("status", "")),
    }


def global_lease_summary(project_root: Path) -> dict[str, str] | None:
    lease = find_global_lease(project_root)
    if lease is None:
        return None
    return {
        "featureId": str(lease.get("_featureId") or lease.get("featureId", "")),
        "sliceId": str(lease.get("sliceId", "")),
        "executionId": str(lease.get("executionId", "")),
    }


def slices_status(project_root: Path, feature_id: str) -> list[dict[str, str]]:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    approved_path = archive / "04-plan/slice-plan.approved.json"
    if not approved_path.is_file():
        return []
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    states = {sid: data.get("state", "pending") for sid, data in load_slice_states(project_root, feature_id).items()}
    eligibility = compute_slice_eligibility(approved, states)
    result: list[dict[str, str]] = []
    for item in approved.get("slices", []):
        if not isinstance(item, dict):
            continue
        sid = str(item.get("id", ""))
        result.append({"id": sid, "state": states.get(sid, "pending"), "eligibility": eligibility.get(sid, "waiting")})
    return result


def completion_claim(project_root: Path, feature_id: str, meta: dict[str, Any]) -> dict[str, str]:
    lifecycle = meta.get("lifecycle")
    if lifecycle == "frozen":
        return {"claim": "frozen", "reason": "交付记录已封存"}
    lease = read_lease(project_root, feature_id)
    if lease and lease.get("status") == "circuit_open":
        return {"claim": "blocked", "reason": "存在熔断租约"}
    states = load_slice_states(project_root, feature_id)
    if any(data.get("state") == "released" for data in states.values()):
        return {"claim": "blocked", "reason": "存在 released 切片"}
    profile = meta.get("profile", "delivery")
    if profile == "ui" and lifecycle != "frozen":
        val = meta.get("validation", {})
        if isinstance(val, dict) and val.get("conclusion") == "passed":
            return {"claim": "in_progress", "reason": "等待用户验收"}
    return {"claim": "in_progress", "reason": "交付进行中"}
