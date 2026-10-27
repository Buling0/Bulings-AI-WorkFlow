from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from bulings.delivery.archive import default_now, delivery_status, init_delivery, list_deliveries
from bulings.delivery.documents import assert_fresh, confirm_change, refresh_queue
from bulings.delivery.errors import DeliveryError, emit_failure, emit_success
from bulings.delivery.open_cmd import open_delivery
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
    except DeliveryError as error:
        return emit_failure(error)

    return emit_failure(DeliveryError(code="UNKNOWN_COMMAND", message=f"未知命令: {args.command}", exit_code=2))


def _cmd_init(project: Path, args: DeliveryArgs) -> int:
    if not args.feature_id:
        return emit_failure(DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2))
    if args.title is None:
        return emit_failure(DeliveryError(code="MISSING_TITLE", message="缺少 --title", exit_code=2))
    result = init_delivery(project, args.feature_id, args.title, now=default_now)
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
            }
        )
    else:
        deliveries, invalid = list_deliveries(project)
        emit_success(
            {
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
        choices=["init", "status", "confirm-change", "refresh-queue", "assert-fresh", "rules", "open"],
    )
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--feature-id", dest="feature_id")
    parser.add_argument("--title")
    parser.add_argument("--document-id", dest="document_ids", action="append", default=[])
    parser.add_argument("--semantic-change", dest="semantic_change", type=_parse_bool)
    parser.add_argument("--action")
    parser.add_argument("--query")
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
        help=namespace.help,
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise DeliveryError(code="INVALID_ARGS", message=f"无法解析布尔值: {value}", exit_code=2)
