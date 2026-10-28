from __future__ import annotations

import json
from pathlib import Path

from bulings.delivery.design_flow import design_ready
from bulings.delivery.documents import confirm_change, read_managed_document
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.lease_store import find_global_lease
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import REQUIREMENTS_REL, list_requirement_scene_names
from bulings.delivery.slice_state import load_slice_states
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.workspace import file_digest

VALIDATION_REL = "06-validation/README.md"
INTEGRATION = "06-validation/integration.json"
CANDIDATES = "05-implementation/candidates"


def begin_validation(project_root: Path, feature_id: str, *, now) -> str:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = read_feature_meta(archive / "feature.json")
    if find_global_lease(project_root):
        raise DeliveryError(code="LEASE_ACTIVE", message="存在活动租约", exit_code=1)
    if meta.get("lifecycle") not in {"active", "validating"}:
        raise DeliveryError(code="INVALID_LIFECYCLE", message="生命周期不允许", exit_code=1)
    _require_all_accepted(project_root, feature_id, archive)
    design_ready(project_root, feature_id)
    if meta.get("lifecycle") == "validating":
        return "unchanged"
    meta = dict(meta)
    meta["lifecycle"] = "validating"
    meta["updatedAt"] = format_iso8601(now())
    (archive / "feature.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return "begun"


def record_validation(
    project_root: Path,
    feature_id: str,
    conclusion: str,
    unverified: str,
    risks: str,
    *,
    now,
) -> None:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = read_feature_meta(archive / "feature.json")
    if meta.get("lifecycle") != "validating":
        raise DeliveryError(code="INVALID_LIFECYCLE", message="不在 validating", exit_code=1)
    if conclusion not in {"passed", "failed"}:
        raise DeliveryError(code="INVALID_CONCLUSION", message="conclusion 无效", exit_code=2)
    if unverified not in {"none", "documented"} or risks not in {"none", "documented"}:
        raise DeliveryError(code="INVALID_ARGS", message="unverified/risks 无效", exit_code=2)
    _validate_validation_body(archive, conclusion, unverified, risks)
    if conclusion == "passed":
        _check_workspace_drift(project_root, feature_id, archive)
    validation = meta.get("validation")
    if not isinstance(validation, dict):
        validation = {}
    validation = dict(validation)
    validation["conclusion"] = conclusion
    validation["unverifiedBoundaries"] = "none" if unverified == "none" else "documented"
    validation["residualRisks"] = "none" if risks == "none" else "documented"
    meta = dict(meta)
    meta["validation"] = validation
    meta["updatedAt"] = format_iso8601(now())
    (archive / "feature.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if conclusion == "passed":
        confirm_change(
            project_root,
            feature_id,
            [document_id(feature_id, "validation.overview")],
            True,
            now=now,
        )
        _write_integration(project_root, feature_id, archive)


def freeze_delivery(project_root: Path, feature_id: str, *, now) -> str:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    meta = read_feature_meta(archive / "feature.json")
    if meta.get("lifecycle") == "frozen":
        return "unchanged"
    if meta.get("lifecycle") != "validating":
        raise DeliveryError(code="INVALID_LIFECYCLE", message="不在 validating", exit_code=1)
    validation = meta.get("validation", {})
    if validation.get("conclusion") != "passed":
        raise DeliveryError(code="NOT_READY", message="验证未通过", exit_code=1)
    if validation.get("unverifiedBoundaries") == "pending" or validation.get("residualRisks") == "pending":
        raise DeliveryError(code="NOT_READY", message="边界字段未就绪", exit_code=1)
    if find_global_lease(project_root):
        raise DeliveryError(code="LEASE_ACTIVE", message="存在租约", exit_code=1)
    profile = meta.get("profile", "delivery")
    if profile == "ui":
        from bulings.delivery.ui_flow import ui_freeze_checks

        ui_freeze_checks(project_root, feature_id)
    _verify_integration(archive, project_root, feature_id)
    meta = dict(meta)
    meta["lifecycle"] = "frozen"
    meta["frozenAt"] = format_iso8601(now())
    meta["updatedAt"] = meta["frozenAt"]
    (archive / "feature.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return "frozen"


def _require_all_accepted(project_root: Path, feature_id: str, archive: Path) -> None:
    approved_path = archive / "04-plan/slice-plan.approved.json"
    if not approved_path.is_file():
        raise DeliveryError(code="SLICES_INCOMPLETE", message="没有批准的切片方案", exit_code=1)
    approved = json.loads(approved_path.read_text(encoding="utf-8"))
    states = load_slice_states(project_root, feature_id)
    for item in approved.get("slices", []):
        sid = item.get("id")
        state = states.get(sid, {}).get("state", "pending")
        if state != "accepted":
            raise DeliveryError(code="SLICES_INCOMPLETE", message=f"切片未接受: {sid}", exit_code=1)


def _validate_validation_body(archive: Path, conclusion: str, unverified: str, risks: str) -> None:
    _meta, body = read_managed_document(archive / VALIDATION_REL)
    if "待填写" in body:
        raise DeliveryError(code="MATERIAL_MISSING", message="验证总览未就绪", exit_code=1)
    _req_meta, req_body = read_managed_document(archive / REQUIREMENTS_REL)
    scenes = list_requirement_scene_names(req_body)
    for scene in scenes:
        if f"### {scene}" not in body:
            raise DeliveryError(code="MATERIAL_MISSING", message=f"缺少场景节: {scene}", exit_code=1)
    if conclusion == "passed":
        for scene in scenes:
            section = body.split(f"### {scene}", 1)[-1].split("###", 1)[0]
            if "偏差：无" not in section and "偏差: 无" not in section:
                raise DeliveryError(code="DEVIATION", message=f"场景 {scene} 偏差不是无", exit_code=1)
        if unverified == "none" and "## 未验证边界" in body and "无" not in body.split("## 未验证边界", 1)[1].split("##", 1)[0]:
            raise DeliveryError(code="MATERIAL_MISSING", message="未验证边界与参数不一致", exit_code=1)
        if risks == "none" and "## 残留风险" in body and "无" not in body.split("## 残留风险", 1)[1].split("##", 1)[0]:
            raise DeliveryError(code="MATERIAL_MISSING", message="残留风险与参数不一致", exit_code=1)


def _accepted_candidates(archive: Path, feature_id: str, project_root: Path) -> list[tuple[str, dict]]:
    states = load_slice_states(project_root, feature_id)
    result: list[tuple[str, dict]] = []
    cand_dir = archive / CANDIDATES
    for sid, data in states.items():
        if data.get("state") != "accepted":
            continue
        cid = data.get("candidateId")
        if not cid:
            continue
        path = cand_dir / f"{cid}.json"
        if path.is_file():
            result.append((cid, json.loads(path.read_text(encoding="utf-8"))))
    return sorted(result, key=lambda x: x[0])


def _check_workspace_drift(project_root: Path, feature_id: str, archive: Path) -> None:
    blockers: list[Blocker] = []
    for _cid, candidate in _accepted_candidates(archive, feature_id, project_root):
        files = candidate.get("files") or {}
        if not isinstance(files, dict):
            continue
        for rel, digest in files.items():
            path = project_root / str(rel).replace("\\", "/")
            if not path.is_file() or file_digest(path) != str(digest):
                blockers.append(Blocker(code="WORKSPACE_DRIFT", message="候选文件已变化", path=str(rel)))
    if blockers:
        raise DeliveryError(code="WORKSPACE_DRIFT", message="工作区与候选不一致", exit_code=1, blockers=blockers)


def _integration_payload(archive: Path, feature_id: str, project_root: Path) -> dict[str, object]:
    pairs = _accepted_candidates(archive, feature_id, project_root)
    candidate_ids = [cid for cid, _ in pairs]
    digest_parts: list[str] = []
    workspace_parts: list[str] = []
    for cid, candidate in pairs:
        path = archive / CANDIDATES / f"{cid}.json"
        digest_parts.append(path.read_bytes().decode("utf-8"))
        files = candidate.get("files") or {}
        if isinstance(files, dict):
            for rel in sorted(files.keys()):
                workspace_parts.append(f"{rel}:{files[rel]}")
    return {
        "schema": 1,
        "result": "passed",
        "candidateIds": candidate_ids,
        "candidateDigest": content_fingerprint("".join(digest_parts)),
        "workspaceDigest": content_fingerprint("\n".join(workspace_parts)),
    }


def _write_integration(project_root: Path, feature_id: str, archive: Path) -> None:
    payload = _integration_payload(archive, feature_id, project_root)
    (archive / INTEGRATION).parent.mkdir(parents=True, exist_ok=True)
    (archive / INTEGRATION).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _verify_integration(archive: Path, project_root: Path, feature_id: str) -> None:
    path = archive / INTEGRATION
    if not path.is_file():
        raise DeliveryError(code="NOT_READY", message="缺少 integration.json", exit_code=1)
    stored = json.loads(path.read_text(encoding="utf-8"))
    expected = _integration_payload(archive, feature_id, project_root)
    if stored.get("candidateDigest") != expected["candidateDigest"] or stored.get("workspaceDigest") != expected["workspaceDigest"]:
        raise DeliveryError(code="INTEGRATION_STALE", message="integration 摘要不一致", exit_code=1)
