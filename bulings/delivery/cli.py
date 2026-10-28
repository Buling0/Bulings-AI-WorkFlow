from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from bulings.delivery.archive import default_now, delivery_status, init_delivery, list_deliveries
from bulings.delivery.documents import assert_fresh, confirm_change, refresh_queue
from bulings.delivery.errors import DeliveryError, emit_failure, emit_success
from bulings.delivery.open_cmd import open_delivery
from bulings.delivery.design_flow import (
    design_ready,
    design_review_prompt,
    prepare_design,
    record_design_review,
)
from bulings.delivery.slice_plan import (
    approve_slice_plan,
    check_slice_plan,
    prepare_plan,
    prepare_slice_plan,
)
from bulings.delivery.requirements_flow import approve_requirements, cold_read_prompt
from bulings.delivery.rules import load_delivery_rules


class DeliveryParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DeliveryError(code="INVALID_ARGS", message=message, exit_code=2)


@dataclass
class DeliveryArgs:
    command: str | None
    project: str | None
    feature_id: str | None
    title: str | None
    document_ids: list[str]
    semantic_change: bool | None
    action: str | None
    query: str | None
    question: str | None
    decision: str | None
    locator: str | None
    user_confirmation: str | None
    summary: str | None
    digest: str | None
    profile: str | None
    slice_id: str | None
    execution_id: str | None
    validation_result: str | None
    covered_validation: list[str]
    paths: list[str]
    next_execution_id: str | None
    rule: str | None
    candidate_id: str | None
    conclusion: str | None
    unverified: str | None
    risks: str | None
    stage: str | None
    snapshot_id: str | None
    execute: bool
    scenarios: list[str]
    input_path: str | None
    help: bool


def dispatch_delivery(argv: list[str]) -> int:
    try:
        args = _parse_delivery_args(argv)
    except DeliveryError as error:
        return emit_failure(error)

    if args.help or not args.command:
        print_delivery_help()
        return 0 if args.help else 2

    if not args.project:
        return emit_failure(
            DeliveryError(code="MISSING_PROJECT", message="缺少 --project <Unity工程>", exit_code=2)
        )

    project = Path(os.path.abspath(args.project))
    try:
        if args.command == "init":
            return _cmd_init(project, args)
        if args.command == "status":
            return _cmd_status(project, args)
        if args.command == "confirm-change":
            return _cmd_confirm_change(project, args)
        if args.command == "refresh-queue":
            return _cmd_refresh_queue(project, args)
        if args.command == "assert-fresh":
            return _cmd_assert_fresh(project, args)
        if args.command == "rules":
            return _cmd_rules(project, args)
        if args.command == "open":
            return _cmd_open(project, args)
        if args.command == "cold-read-prompt":
            return _cmd_cold_read_prompt(project, args)
        if args.command == "approve-requirements":
            return _cmd_approve_requirements(project, args)
        if args.command == "prepare-design":
            return _cmd_prepare_design(project, args)
        if args.command == "design-review-prompt":
            return _cmd_design_review_prompt(project, args)
        if args.command == "record-design-review":
            return _cmd_record_design_review(project, args)
        if args.command == "design-ready":
            return _cmd_design_ready(project, args)
        from bulings.delivery.extra_cli_handlers import handle

        extra = handle(project, args.command, args)
        if extra is not None:
            return extra
    except DeliveryError as error:
        return emit_failure(error)

    return emit_failure(DeliveryError(code="UNKNOWN_COMMAND", message=f"未知命令: {args.command}", exit_code=2))


def _cmd_init(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if args.title is None:
        return emit_failure(DeliveryError(code="MISSING_TITLE", message="缺少 --title", exit_code=2))
    profile = args.profile or "delivery"
    result = init_delivery(project, args.feature_id, args.title, profile=profile, now=default_now)
    emit_success({"status": result.status, "featureId": result.feature_id, "archive": result.archive})
    return 0


def _cmd_status(project: Path, args: DeliveryArgs) -> int:
    if args.feature_id:
        detail = delivery_status(project, args.feature_id)
        emit_success(
            {
                "featureId": detail.feature_id,
                "title": detail.title,
                "profile": detail.profile,
                "lifecycle": detail.lifecycle,
                "archive": detail.archive,
                "updatedAt": detail.updated_at,
                "documentErrors": detail.document_errors,
                "approvalState": detail.approval_state,
                "slicePlan": detail.slice_plan,
                "sliceEligibility": detail.slice_eligibility,
                "lease": detail.lease,
                "slices": detail.slices,
                "completion": detail.completion,
            }
        )
    else:
        from bulings.delivery.status_extra import global_lease_summary

        deliveries, invalid = list_deliveries(project)
        emit_success(
            {
                "lease": global_lease_summary(project),
                "deliveries": [
                    {
                        "featureId": item.feature_id,
                        "title": item.title,
                        "lifecycle": item.lifecycle,
                        "updatedAt": item.updated_at,
                    }
                    for item in deliveries
                ],
                "invalid": invalid,
            }
        )
    return 0


def _cmd_confirm_change(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if not args.document_ids:
        return emit_failure(DeliveryError(code="MISSING_DOCUMENT", message="缺少 --document-id", exit_code=2))
    if args.semantic_change is None:
        return emit_failure(
            DeliveryError(code="MISSING_SEMANTIC_CHANGE", message="缺少 --semantic-change", exit_code=2)
        )
    result = confirm_change(
        project,
        args.feature_id,
        args.document_ids,
        args.semantic_change,
        now=default_now,
    )
    payload: dict[str, object] = {"status": result.status}
    if result.documents:
        payload["documents"] = result.documents
    emit_success(payload)
    return 0


def _cmd_refresh_queue(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    queue = refresh_queue(project, args.feature_id)
    emit_success({"queue": [{"documentId": item.document_id, "reason": item.reason} for item in queue]})
    return 0


def _cmd_rules(project: Path, args: DeliveryArgs) -> int:
    if not args.action:
        return emit_failure(DeliveryError(code="MISSING_ACTION", message="缺少 --action", exit_code=2))
    result = load_delivery_rules(project, args.action)
    emit_success(
        {
            "action": result.action,
            "rules": [
                {"path": item.path, "sha256": item.sha256, "body": item.body}
                for item in result.rules
            ],
        }
    )
    return 0


def _cmd_cold_read_prompt(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if args.question is None:
        return emit_failure(DeliveryError(code="MISSING_QUESTION", message="缺少 --question", exit_code=2))
    result = cold_read_prompt(project, args.feature_id, args.question)
    emit_success(
        {
            "featureId": result.feature_id,
            "role": result.role,
            "prompt": result.prompt,
            "materials": result.materials,
        }
    )
    return 0


def _cmd_approve_requirements(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if not args.decision:
        return emit_failure(DeliveryError(code="MISSING_DECISION", message="缺少 --decision", exit_code=2))
    if args.locator is None:
        return emit_failure(DeliveryError(code="MISSING_LOCATOR", message="缺少 --locator", exit_code=2))
    if args.user_confirmation is None:
        return emit_failure(
            DeliveryError(code="MISSING_CONFIRMATION", message="缺少 --user-confirmation", exit_code=2)
        )
    record = approve_requirements(
        project,
        args.feature_id,
        args.decision,
        args.locator,
        args.user_confirmation,
        now=default_now,
    )
    emit_success({"status": "recorded", "approval": record})
    return 0


def _cmd_prepare_design(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    status = prepare_design(project, args.feature_id, now=default_now)
    emit_success({"status": status, "featureId": args.feature_id})
    return 0


def _cmd_design_review_prompt(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    result = design_review_prompt(project, args.feature_id)
    emit_success(
        {
            "featureId": result.feature_id,
            "role": result.role,
            "prompt": result.prompt,
            "materials": result.materials,
        }
    )
    return 0


def _cmd_record_design_review(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if not args.decision:
        return emit_failure(DeliveryError(code="MISSING_DECISION", message="缺少 --decision", exit_code=2))
    if args.summary is None:
        return emit_failure(DeliveryError(code="MISSING_SUMMARY", message="缺少 --summary", exit_code=2))
    record = record_design_review(
        project,
        args.feature_id,
        args.decision,
        args.summary,
        now=default_now,
    )
    emit_success({"status": "recorded", "approval": record})
    return 0


def _cmd_prepare_plan(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    status = prepare_plan(project, args.feature_id, now=default_now)
    emit_success({"status": status, "featureId": args.feature_id})
    return 0


def _cmd_prepare_slice_plan(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    status = prepare_slice_plan(project, args.feature_id)
    emit_success({"status": status, "featureId": args.feature_id})
    return 0


def _cmd_check_slice_plan(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    result = check_slice_plan(project, args.feature_id)
    emit_success({"status": result.status, "slices": result.slices, "digest": result.digest})
    return 0


def _cmd_approve_slice_plan(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if not args.digest:
        return emit_failure(DeliveryError(code="MISSING_DIGEST", message="缺少 --digest", exit_code=2))
    status = approve_slice_plan(project, args.feature_id, args.digest, now=default_now)
    emit_success({"status": status, "featureId": args.feature_id})
    return 0


def _cmd_design_ready(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    result = design_ready(project, args.feature_id)
    emit_success(result)
    return 0


def _cmd_open(project: Path, args: DeliveryArgs) -> int:
    if args.query is None:
        return emit_failure(DeliveryError(code="MISSING_QUERY", message="缺少 --query", exit_code=2))
    result = open_delivery(project, args.query)
    emit_success(result.payload)
    return 0


def _cmd_assert_fresh(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if not args.document_ids:
        return emit_failure(DeliveryError(code="MISSING_DOCUMENT", message="缺少 --document-id", exit_code=2))
    result = assert_fresh(project, args.feature_id, args.document_ids)
    emit_success({"status": result.status})
    return 0


def print_delivery_help() -> None:
    print(
        """交付流命令
  bulings delivery init --project <Unity工程> --feature-id <标识> --title <标题>
  bulings delivery status --project <Unity工程> [--feature-id <标识>]
  bulings delivery confirm-change --project <工程> --feature-id <id> --document-id <标识> [--document-id ...] --semantic-change true|false
  bulings delivery refresh-queue --project <工程> --feature-id <id>
  bulings delivery assert-fresh --project <工程> --feature-id <id> --document-id <标识> [--document-id ...]
  bulings delivery rules --project <工程> --action <动作名>
  bulings delivery open --project <工程> --query <标题或标识>
  bulings delivery cold-read-prompt --project <工程> --feature-id <id> --question <入口问题>
  bulings delivery approve-requirements --project <工程> --feature-id <id> --decision approve|reject --locator <位置> --user-confirmation <用户原文>
  bulings delivery prepare-design --project <工程> --feature-id <id>
  bulings delivery design-review-prompt --project <工程> --feature-id <id>
  bulings delivery record-design-review --project <工程> --feature-id <id> --decision pass|fail|unverified --summary <结论>
  bulings delivery design-ready --project <工程> --feature-id <id>
  bulings delivery prepare-plan --project <工程> --feature-id <id>
  bulings delivery prepare-slice-plan --project <工程> --feature-id <id>
  bulings delivery check-slice-plan --project <工程> --feature-id <id>
  bulings delivery approve-slice-plan --project <工程> --feature-id <id> --digest sha256:...

退出码
  0  成功
  1  可诊断的业务或环境失败
  2  参数不合法"""
    )


def _parse_delivery_args(argv: list[str]) -> DeliveryArgs:
    parser = DeliveryParser(prog="bulings delivery", add_help=False, allow_abbrev=False)
    parser.add_argument(
        "command",
        nargs="?",
        choices=[
            "init",
            "status",
            "confirm-change",
            "refresh-queue",
            "assert-fresh",
            "rules",
            "open",
            "cold-read-prompt",
            "approve-requirements",
            "prepare-design",
            "design-review-prompt",
            "record-design-review",
            "design-ready",
            "prepare-plan",
            "prepare-slice-plan",
            "check-slice-plan",
            "approve-slice-plan",
            "prepare-task-package",
            "check-task-package",
            "start-slice",
            "checkpoint-slice",
            "submit-slice",
            "review-prompt",
            "review-slice",
            "open-circuit",
            "resolve-slice",
            "interrupt-slice",
            "amend-scope",
            "begin-validation",
            "record-validation",
            "freeze-delivery",
            "snapshot-save",
            "snapshot-list",
            "snapshot-restore",
            "prepare-ui-baseline",
            "check-ui-baseline",
            "approve-ui-baseline",
            "record-acceptance",
            "publish-ui",
            "approve-final",
        ],
    )
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--profile", default="delivery")
    parser.add_argument("--feature-id", dest="feature_id")
    parser.add_argument("--slice-id", dest="slice_id")
    parser.add_argument("--execution-id", dest="execution_id")
    parser.add_argument("--next-execution-id", dest="next_execution_id")
    parser.add_argument("--validation-result", dest="validation_result")
    parser.add_argument("--covered-validation", dest="covered_validation", action="append", default=[])
    parser.add_argument("--path", dest="paths", action="append", default=[])
    parser.add_argument("--reason")
    parser.add_argument("--authorization")
    parser.add_argument("--rule")
    parser.add_argument("--candidate-id", dest="candidate_id")
    parser.add_argument("--conclusion")
    parser.add_argument("--unverified")
    parser.add_argument("--risks")
    parser.add_argument("--stage")
    parser.add_argument("--name")
    parser.add_argument("--snapshot-id", dest="snapshot_id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--scenario", dest="scenarios", action="append", default=[])
    parser.add_argument("--input", dest="input_path")
    parser.add_argument("--title")
    parser.add_argument("--document-id", dest="document_ids", action="append", default=[])
    parser.add_argument("--semantic-change", dest="semantic_change", type=_parse_bool)
    parser.add_argument("--action")
    parser.add_argument("--query")
    parser.add_argument("--question")
    parser.add_argument("--decision")
    parser.add_argument("--locator")
    parser.add_argument("--user-confirmation", dest="user_confirmation")
    parser.add_argument("--summary")
    parser.add_argument("--digest")
    namespace = parser.parse_args(argv)
    return DeliveryArgs(
        command=namespace.command,
        project=namespace.project,
        feature_id=namespace.feature_id,
        title=namespace.title,
        document_ids=list(namespace.document_ids or []),
        semantic_change=namespace.semantic_change,
        action=namespace.action,
        query=namespace.query,
        question=namespace.question,
        decision=namespace.decision,
        locator=namespace.locator,
        user_confirmation=namespace.user_confirmation,
        summary=namespace.summary,
        digest=namespace.digest,
        profile=namespace.profile,
        slice_id=namespace.slice_id,
        execution_id=namespace.execution_id,
        validation_result=namespace.validation_result,
        covered_validation=list(namespace.covered_validation or []),
        paths=list(namespace.paths or []),
        next_execution_id=namespace.next_execution_id,
        rule=namespace.rule,
        candidate_id=namespace.candidate_id,
        conclusion=namespace.conclusion,
        unverified=namespace.unverified,
        risks=namespace.risks,
        stage=namespace.stage,
        snapshot_id=namespace.snapshot_id,
        execute=namespace.execute,
        scenarios=list(namespace.scenarios or []),
        input_path=namespace.input_path,
        help=namespace.help,
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise DeliveryError(code="INVALID_ARGS", message=f"无法解析布尔值: {value}", exit_code=2)
