from __future__ import annotations

import json
from pathlib import Path

from bulings.delivery.documents import read_managed_document
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.requirements_flow import REQUIREMENTS_REL, list_requirement_scene_names
from bulings.delivery.slice_state import load_slice_states
from bulings.delivery.time_util import format_iso8601

UI_BASELINE = "02-investigation/ui-baseline.json"
ACCEPTANCE = "06-validation/acceptance.json"
UI_HTML = "06-validation/ui-delivery.html"
CANDIDATES = "05-implementation/candidates"


def ui_start_checks(project_root: Path, feature_id: str, package: dict) -> list[Blocker]:
    blockers: list[Blocker] = []
    scenarios = package.get("scenarios") or []
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    approvals = (meta.get("approvals") or {}).get("uiBaseline") or {}
    approved = approvals.get("scenarios") or {}
    digest = approvals.get("fileDigest")
    current = content_fingerprint((archive / UI_BASELINE).read_bytes().decode("utf-8")) if (archive / UI_BASELINE).is_file() else ""
    for scene in scenarios:
        entry = approved.get(scene) or {}
        if entry.get("decision") != "approve":
            blockers.append(Blocker(code="UI_NOT_APPROVED", message=f"场景未批准: {scene}"))
        elif digest and current and digest != current:
            blockers.append(Blocker(code="UI_STALE", message=f"场景批准已过期: {scene}"))
    return blockers


def prepare_ui_baseline(project_root: Path, feature_id: str) -> str:
    archive = _require_ui_profile(project_root, feature_id)
    path = archive / UI_BASELINE
    if path.is_file():
        return str(path.relative_to(project_root)).replace("\\", "/")
    payload = {"schema": 1, "items": [], "excludedSources": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return str(path.relative_to(project_root)).replace("\\", "/")


def check_ui_baseline(project_root: Path, feature_id: str) -> list[dict[str, object]]:
    archive = _require_ui_profile(project_root, feature_id)
    data = json.loads((archive / UI_BASELINE).read_text(encoding="utf-8"))
    return [{"scenario": item.get("scenario"), "ready": _scenario_ready(item)} for item in data.get("items", [])]


def approve_ui_baseline(
    project_root: Path,
    feature_id: str,
    scenarios: list[str],
    decision: str,
    locator: str,
    user_confirmation: str,
    *,
    now,
) -> None:
    archive = _require_ui_profile(project_root, feature_id)
    if decision != "approve":
        raise DeliveryError(code="INVALID_DECISION", message="仅支持 approve", exit_code=2)
    if not locator.strip() or not user_confirmation.strip():
        raise DeliveryError(code="INVALID_ARGS", message="locator 与 user-confirmation 必填", exit_code=2)
    ready_map = {str(x["scenario"]): bool(x["ready"]) for x in check_ui_baseline(project_root, feature_id)}
    for scene in scenarios:
        if not ready_map.get(scene):
            raise DeliveryError(code="NOT_READY", message=f"场景未就绪: {scene}", exit_code=1)
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    approvals = dict(meta.get("approvals") or {})
    ui = dict(approvals.get("uiBaseline") or {})
    ui_scenarios = dict(ui.get("scenarios") or {})
    file_digest = content_fingerprint((archive / UI_BASELINE).read_bytes().decode("utf-8"))
    for scene in scenarios:
        ui_scenarios[scene] = {
            "decision": "approve",
            "locator": locator.strip(),
            "userConfirmation": user_confirmation.strip(),
            "approvedAt": format_iso8601(now()),
        }
    ui["scenarios"] = ui_scenarios
    ui["fileDigest"] = file_digest
    approvals["uiBaseline"] = ui
    meta["approvals"] = approvals
    meta["updatedAt"] = format_iso8601(now())
    (archive / "feature.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def record_acceptance(project_root: Path, feature_id: str, payload: dict) -> None:
    archive = _require_ui_profile(project_root, feature_id)
    if payload.get("schema") != 1:
        raise DeliveryError(code="INVALID_INPUT", message="acceptance schema 无效", exit_code=2)
    path = archive / ACCEPTANCE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def publish_ui(project_root: Path, feature_id: str) -> dict[str, object]:
    archive = _require_ui_profile(project_root, feature_id)
    acceptance_path = archive / ACCEPTANCE
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8")) if acceptance_path.is_file() else {"scenarios": [], "smoke": {}}
    _meta, req_body = read_managed_document(archive / REQUIREMENTS_REL)
    scene_names = list_requirement_scene_names(req_body)
    lines = ["<html><body><h1>界面验收</h1>"]
    states = load_slice_states(project_root, feature_id)
    has_accepted = any(v.get("state") == "accepted" for v in states.values())
    if not has_accepted:
        lines.append("<p>尚未形成可封存结果</p>")
    for item in acceptance.get("scenarios") or []:
        scenario = item.get("scenario", "")
        status = item.get("status", "unverified")
        label = "未验证" if status == "unverified" else status
        lines.append(f"<section><h2>{scenario}</h2><p>{label}</p></section>")
    lines.append("</body></html>")
    html = "\n".join(lines)
    (archive / UI_HTML).write_text(html, encoding="utf-8", newline="\n")
    delivery_ready = _delivery_ready(acceptance, scene_names)
    return {
        "deliveryReady": delivery_ready,
        "path": str((archive / UI_HTML).relative_to(project_root)).replace("\\", "/"),
    }


def approve_final(
    project_root: Path,
    feature_id: str,
    decision: str,
    locator: str,
    user_confirmation: str,
    *,
    now,
) -> None:
    archive = _require_ui_profile(project_root, feature_id)
    if decision != "approve":
        raise DeliveryError(code="INVALID_DECISION", message="仅支持 approve", exit_code=2)
    if not user_confirmation.strip():
        raise DeliveryError(code="INVALID_ARGS", message="user-confirmation 必填", exit_code=2)
    pub = publish_ui(project_root, feature_id)
    if not pub.get("deliveryReady"):
        raise DeliveryError(code="UI_NOT_READY", message="界面未就绪", exit_code=1)
    html_path = archive / UI_HTML
    html_digest = content_fingerprint(html_path.read_bytes().decode("utf-8"))
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    approvals = dict(meta.get("approvals") or {})
    approvals["final"] = {
        "decision": "approve",
        "locator": locator.strip(),
        "userConfirmation": user_confirmation.strip(),
        "htmlDigest": html_digest,
        "approvedAt": format_iso8601(now()),
    }
    meta["approvals"] = approvals
    meta["updatedAt"] = format_iso8601(now())
    (archive / "feature.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def ui_freeze_checks(project_root: Path, feature_id: str) -> None:
    pub = publish_ui(project_root, feature_id)
    if not pub.get("deliveryReady"):
        raise DeliveryError(code="UI_NOT_READY", message="界面未就绪", exit_code=1)
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    final = (meta.get("approvals") or {}).get("final") or {}
    if final.get("decision") != "approve" or not final.get("userConfirmation"):
        raise DeliveryError(code="UI_NOT_APPROVED", message="缺少最终验收", exit_code=1)
    html_digest = content_fingerprint((archive / UI_HTML).read_bytes().decode("utf-8"))
    if final.get("htmlDigest") != html_digest:
        raise DeliveryError(code="UI_STALE", message="HTML 摘要已变化", exit_code=1)


def approve_final_delivery_profile(project_root: Path, feature_id: str) -> None:
    meta = json.loads((project_root / ".bulings/deliveries" / feature_id / "feature.json").read_text(encoding="utf-8"))
    if meta.get("profile", "delivery") != "ui":
        raise DeliveryError(code="PROFILE_MISMATCH", message="仅 ui profile 可用", exit_code=1)


def _require_ui_profile(project_root: Path, feature_id: str) -> Path:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    if meta.get("profile") != "ui":
        raise DeliveryError(code="PROFILE_MISMATCH", message="需要 profile ui", exit_code=1)
    return archive


def _delivery_ready(acceptance: dict, scene_names: list[str]) -> bool:
    smoke = acceptance.get("smoke") or {}
    if smoke.get("status") != "passed":
        return False
    note = str(smoke.get("note") or "").strip()
    smoke_evidence = smoke.get("evidence") or []
    if not note or not isinstance(smoke_evidence, list) or not smoke_evidence:
        return False
    by_name = {str(x.get("scenario")): x for x in acceptance.get("scenarios") or [] if isinstance(x, dict)}
    for scene in scene_names:
        item = by_name.get(scene)
        if not item or item.get("level") != "runtime" or item.get("status") != "passed":
            return False
        evidence = item.get("evidence") or []
        if not evidence:
            return False
    return True


def _scenario_ready(item: dict) -> bool:
    for key in ("prefabs", "protocols", "configurations", "requirement"):
        values = item.get(key)
        if isinstance(values, list):
            for entry in values:
                if entry.get("status") in {"missing", "ambiguous"}:
                    return False
        elif isinstance(values, dict) and values.get("status") in {"missing", "ambiguous"}:
            return False
    return True
