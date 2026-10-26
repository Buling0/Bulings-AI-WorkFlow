from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

from bulings.config import RunOverrides
from bulings.install import install_workflow, is_unity_project

HELP_TEXT = """用法
  bulings init --project <Unity工程>
  bulings run --project <Unity工程> --design <策划案> --prefab <预制体> [--prefab <预制体> ...] [--name <功能名>] [--dev-spec <路径>] [--feature-doc <路径>] [--no-dev-spec] [--no-feature-doc] [--model <模型>]
  bulings resume --project <Unity工程> --run <slug>

环境变量
  CURSOR_API_KEY   Cursor 用户 API key

退出码
  0  完成
  1  未能启动（参数、配置、密钥、独游模式或 CursorAgentError）
  2  已开始但没有完成（Agent 失败、任务阻塞或 tasks.json 不合法）"""


class BulingsUsageError(Exception):
    def __init__(self, message: str, show_help: bool = False) -> None:
        super().__init__(message)
        self.show_help = show_help


class BulingsParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        translated, show_help = _translate_argparse_error(message)
        raise BulingsUsageError(translated, show_help)


@dataclass
class ParsedArgs:
    command: str | None = None
    project: str | None = None
    design: str | None = None
    prefabs: list[str] = field(default_factory=list)
    name: str | None = None
    dev_spec: str | None = None
    feature_doc: str | None = None
    no_dev_spec: bool = False
    no_feature_doc: bool = False
    model: str | None = None
    run: str | None = None
    help: bool = False


def main(argv: list[str] | None = None) -> int:
    try:
        return dispatch(sys.argv[1:] if argv is None else argv)
    except BulingsUsageError as error:
        print(error, file=sys.stderr)
        if error.show_help:
            print_help()
        return 1
    except Exception as error:
        if _is_cursor_agent_error(error):
            retryable = str(getattr(error, "is_retryable", False)).lower()
            message = getattr(error, "message", None) or str(error)
            print(f"启动失败：{message}，可重试={retryable}", file=sys.stderr)
            return 1
        print(str(error), file=sys.stderr)
        return 1


def entry() -> None:
    sys.exit(main())


def dispatch(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.help or not args.command:
        print_help()
        return 0 if args.help else 1

    if not args.project:
        print("缺少 --project <Unity工程>", file=sys.stderr)
        return 1
    project = os.path.abspath(args.project)

    if args.command == "init":
        return init_command(project)
    if args.command == "run":
        return run_command(args, project)
    if args.command == "resume":
        return resume_command(args, project)

    print(f"未知命令: {args.command}", file=sys.stderr)
    print_help()
    return 1


def init_command(project: str) -> int:
    if not is_unity_project(project):
        print(f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {project}", file=sys.stderr)
        return 1
    result = install_workflow(project)
    print(f"已安装 Skill 到 {os.path.join(project, '.cursor', 'skills')}")
    config_path = os.path.join(project, ".bulings", "workflow.yaml")
    if result.config_written:
        print(f"已写入 {config_path}")
    else:
        print(f"已保留现有 {config_path}")
    return 0


def run_command(args: ParsedArgs, project: str) -> int:
    if not args.design:
        print("缺少 --design <策划案>", file=sys.stderr)
        return 1
    if not args.prefabs:
        print("至少提供一个 --prefab <预制体>", file=sys.stderr)
        return 1
    from bulings.runner import RunCommand, run_workflow

    return run_workflow(
        RunCommand(
            project=project,
            design=args.design,
            prefabs=args.prefabs,
            name=args.name,
            overrides=RunOverrides(
                model=args.model,
                dev_spec_path=args.dev_spec,
                feature_doc_path=args.feature_doc,
                no_dev_spec=args.no_dev_spec,
                no_feature_doc=args.no_feature_doc,
            ),
        )
    )


def resume_command(args: ParsedArgs, project: str) -> int:
    if not args.run:
        print("缺少 --run <slug>", file=sys.stderr)
        return 1
    from bulings.runner import ResumeCommand, resume_workflow

    return resume_workflow(ResumeCommand(project=project, slug=args.run))


def parse_args(argv: list[str]) -> ParsedArgs:
    parser = _build_parser()
    namespace = parser.parse_args(argv)
    prefab_groups = namespace.prefab or []
    prefabs = [item for group in prefab_groups for item in group]
    return ParsedArgs(
        command=namespace.command,
        project=namespace.project,
        design=namespace.design,
        prefabs=prefabs,
        name=namespace.name,
        dev_spec=namespace.dev_spec,
        feature_doc=namespace.feature_doc,
        no_dev_spec=namespace.no_dev_spec,
        no_feature_doc=namespace.no_feature_doc,
        model=namespace.model,
        run=namespace.run_slug,
        help=namespace.help,
    )


def print_help() -> None:
    print(HELP_TEXT)


def _build_parser() -> BulingsParser:
    parser = BulingsParser(prog="bulings", add_help=False, allow_abbrev=False)
    parser.add_argument("command", nargs="?", choices=["init", "run", "resume"])
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--project")
    parser.add_argument("--design")
    parser.add_argument("--name")
    parser.add_argument("--dev-spec", dest="dev_spec")
    parser.add_argument("--feature-doc", dest="feature_doc")
    parser.add_argument("--model")
    parser.add_argument("--run", dest="run_slug")
    parser.add_argument("--no-dev-spec", action="store_true")
    parser.add_argument("--no-feature-doc", action="store_true")
    parser.add_argument("--prefab", action="append", nargs="+", default=None)
    return parser


def _translate_argparse_error(message: str) -> tuple[str, bool]:
    invalid = re.search(r"invalid choice: '([^']*)'", message)
    if invalid:
        return f"未知命令: {invalid.group(1)}", True
    if "unrecognized arguments" in message:
        rest = message.split(":", 1)[1].strip()
        token = rest.split()[0] if rest else message
        return f"未知参数: {token}", False
    missing = re.search(r"argument (--[\w-]+): expected", message)
    if missing:
        return f"缺少 {missing.group(1)} 的参数", False
    return message, False


def _is_cursor_agent_error(error: BaseException) -> bool:
    return any(cls.__name__ == "CursorAgentError" for cls in type(error).__mro__)
