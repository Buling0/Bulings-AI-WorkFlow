from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

from bulings.delivery.archive import default_now, delivery_status, init_delivery, list_deliveries
from bulings.delivery.errors import DeliveryError, emit_failure, emit_success


class DeliveryParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise DeliveryError(code="INVALID_ARGS", message=message, exit_code=2)


@dataclass
class DeliveryArgs:
    command: str | None
    project: str | None
    feature_id: str | None
    title: str | None
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

    from pathlib import Path

    project = Path(os.path.abspath(args.project))
    try:
        if args.command == "init":
            if not args.feature_id:
                return emit_failure(
                    DeliveryError(code="MISSING_FEATURE_ID", message="缺少 --feature-id", exit_code=2)
                )
            if args.title is None:
                return emit_failure(
                    DeliveryError(code="MISSING_TITLE", message="缺少 --title", exit_code=2)
                )
            result = init_delivery(project, args.feature_id, args.title, now=default_now)
            emit_success(
                {
                    "status": result.status,
                    "featureId": result.feature_id,
                    "archive": result.archive,
                }
            )
            return 0

        if args.command == "status":
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
    except DeliveryError as error:
        return emit_failure(error)

    return emit_failure(DeliveryError(code="UNKNOWN_COMMAND", message=f"未知命令: {args.command}", exit_code=2))


def print_delivery_help() -> None:
    print(
        """交付流命令
  bulings delivery init --project <Unity工程> --feature-id <标识> --title <标题>
  bulings delivery status --project <Unity工程> [--feature-id <标识>]

退出码
  0  成功
  1  可诊断的业务或环境失败
  2  参数不合法"""
    )


def _parse_delivery_args(argv: list[str]) -> DeliveryArgs:
    parser = DeliveryParser(prog="bulings delivery", add_help=False, allow_abbrev=False)
    parser.add_argument("command", nargs="?", choices=["init", "status"])
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--feature-id", dest="feature_id")
    parser.add_argument("--title")
    namespace = parser.parse_args(argv)
    return DeliveryArgs(
        command=namespace.command,
        project=namespace.project,
        feature_id=namespace.feature_id,
        title=namespace.title,
        help=namespace.help,
    )
