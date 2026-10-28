"""Additional delivery CLI command handlers (tasks 07–12)."""

from __future__ import annotations

from pathlib import Path

from bulings.delivery.archive import default_now
from bulings.delivery.circuit_flow import amend_scope, interrupt_slice, open_circuit, resolve_slice
from bulings.delivery.errors import DeliveryError, emit_failure, emit_success
from bulings.delivery.freeze_flow import begin_validation, freeze_delivery, record_validation
from bulings.delivery.lease_flow import (
    check_task_package,
    prepare_task_package,
    start_slice,
)
from bulings.delivery.review_flow import checkpoint_slice, review_prompt, review_slice, submit_slice
from bulings.delivery.slice_plan import approve_slice_plan, check_slice_plan, prepare_plan, prepare_slice_plan
from bulings.delivery.snapshot_flow import snapshot_list, snapshot_restore, snapshot_save
from bulings.delivery.ui_flow import (
    approve_final,
    approve_ui_baseline,
    check_ui_baseline,
    prepare_ui_baseline,
    publish_ui,
    record_acceptance,
)


def handle(project: Path, command: str, args) -> int | None:
    handlers = {
        "prepare-plan": _prepare_plan,
        "prepare-slice-plan": _prepare_slice_plan,
        "check-slice-plan": _check_slice_plan,
        "approve-slice-plan": _approve_slice_plan,
        "prepare-task-package": _prepare_task_package,
        "check-task-package": _check_task_package,
        "start-slice": _start_slice,
        "checkpoint-slice": _checkpoint_slice,
        "submit-slice": _submit_slice,
        "review-prompt": _review_prompt,
        "review-slice": _review_slice,
        "open-circuit": _open_circuit,
        "resolve-slice": _resolve_slice,
        "interrupt-slice": _interrupt_slice,
        "amend-scope": _amend_scope,
        "begin-validation": _begin_validation,
        "record-validation": _record_validation,
        "freeze-delivery": _freeze_delivery,
        "snapshot-save": _snapshot_save,
        "snapshot-list": _snapshot_list,
        "snapshot-restore": _snapshot_restore,
        "prepare-ui-baseline": _prepare_ui_baseline,
        "check-ui-baseline": _check_ui_baseline,
        "approve-ui-baseline": _approve_ui_baseline,
        "record-acceptance": _record_acceptance,
        "publish-ui": _publish_ui,
        "approve-final": _approve_final,
    }
    fn = handlers.get(command)
    if fn is None:
        return None
    return fn(project, args)


def _need_feature(args) -> str | None:
    if not args.feature_id:
        emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
        return None
    return args.feature_id


def _prepare_plan(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"status": prepare_plan(project, fid, now=default_now), "featureId": fid})
    return 0


def _prepare_slice_plan(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"status": prepare_slice_plan(project, fid), "featureId": fid})
    return 0


def _check_slice_plan(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    result = check_slice_plan(project, fid)
    emit_success({"status": result.status, "slices": result.slices, "digest": result.digest})
    return 0


def _approve_slice_plan(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.digest:
        return emit_failure(DeliveryError(code="MISSING_ARGS", message="缺少参数", exit_code=2))
    emit_success({"status": approve_slice_plan(project, fid, args.digest, now=default_now), "featureId": fid})
    return 0


def _prepare_task_package(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.slice_id:
        return 2
    emit_success(prepare_task_package(project, fid, args.slice_id))
    return 0


def _check_task_package(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.slice_id:
        return 2
    digest = check_task_package(project, fid, args.slice_id)
    emit_success({"status": "valid", "packageDigest": digest})
    return 0


def _start_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.slice_id or not args.execution_id:
        return 2
    emit_success(
        {
            "status": start_slice(project, fid, args.slice_id, args.execution_id, now=default_now),
            "featureId": fid,
            "sliceId": args.slice_id,
        }
    )
    return 0


def _checkpoint_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.execution_id or args.summary is None or not args.validation_result:
        return 2
    emit_success(
        {
            "status": checkpoint_slice(
                project,
                fid,
                args.execution_id,
                args.summary,
                args.validation_result,
                covered_validation=args.covered_validation or None,
                now=default_now,
            )
        }
    )
    return 0


def _submit_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.execution_id:
        return 2
    cid = submit_slice(project, fid, args.execution_id, now=default_now)
    emit_success({"status": "submitted", "candidateId": cid})
    return 0


def _review_prompt(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.candidate_id:
        return 2
    emit_success(review_prompt(project, fid, args.candidate_id))
    return 0


def _review_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.candidate_id or not args.execution_id or not args.decision or args.summary is None:
        return 2
    emit_success(
        {
            "decision": review_slice(
                project, fid, args.candidate_id, args.execution_id, args.decision, args.summary, now=default_now
            )
        }
    )
    return 0


def _open_circuit(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.execution_id or not args.rule or args.summary is None:
        return 2
    open_circuit(project, fid, args.execution_id, args.rule, args.summary, now=default_now)
    emit_success({"status": "open"})
    return 0


def _resolve_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.action:
        return 2
    emit_success({"status": resolve_slice(project, fid, args.action, execution_id=args.execution_id)})
    return 0


def _interrupt_slice(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.execution_id:
        return 2
    emit_success({"status": interrupt_slice(project, fid, args.execution_id)})
    return 0


def _amend_scope(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.execution_id or not args.paths or not args.next_execution_id:
        return 2
    amend_scope(
        project,
        fid,
        args.execution_id,
        args.paths,
        args.reason or "",
        args.authorization or "",
        args.next_execution_id,
        now=default_now,
    )
    emit_success({"status": "amended"})
    return 0


def _begin_validation(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"status": begin_validation(project, fid, now=default_now)})
    return 0


def _record_validation(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.conclusion:
        return 2
    record_validation(
        project,
        fid,
        args.conclusion,
        args.unverified or "none",
        args.risks or "none",
        now=default_now,
    )
    emit_success({"status": "recorded"})
    return 0


def _freeze_delivery(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"status": freeze_delivery(project, fid, now=default_now)})
    return 0


def _snapshot_save(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.reason:
        return 2
    emit_success(snapshot_save(project, fid, args.reason, stage=args.stage, name=args.name, now=default_now))
    return 0


def _snapshot_list(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"snapshots": snapshot_list(project, fid)})
    return 0


def _snapshot_restore(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.snapshot_id:
        return 2
    emit_success(snapshot_restore(project, fid, args.snapshot_id, execute=args.execute))
    return 0


def _prepare_ui_baseline(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"path": prepare_ui_baseline(project, fid)})
    return 0


def _check_ui_baseline(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success({"scenarios": check_ui_baseline(project, fid)})
    return 0


def _publish_ui(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid:
        return 2
    emit_success(publish_ui(project, fid))
    return 0


def _approve_ui_baseline(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.scenarios or not args.decision or not args.locator or args.user_confirmation is None:
        return 2
    approve_ui_baseline(
        project,
        fid,
        args.scenarios,
        args.decision,
        args.locator,
        args.user_confirmation,
        now=default_now,
    )
    emit_success({"status": "approved"})
    return 0


def _record_acceptance(project: Path, args) -> int:
    import json

    fid = _need_feature(args)
    if not fid or not args.input_path:
        return 2
    payload = json.loads(Path(args.input_path).read_text(encoding="utf-8"))
    record_acceptance(project, fid, payload)
    emit_success({"status": "recorded"})
    return 0


def _approve_final(project: Path, args) -> int:
    fid = _need_feature(args)
    if not fid or not args.decision or not args.locator or args.user_confirmation is None:
        return 2
    approve_final(project, fid, args.decision, args.locator, args.user_confirmation, now=default_now)
    emit_success({"status": "approved"})
    return 0
