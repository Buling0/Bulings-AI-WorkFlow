from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from bulings.delivery.errors import DeliveryError
from bulings.install import is_unity_project, package_root


@dataclass(frozen=True)
class RuleFile:
    path: str
    sha256: str
    body: str


@dataclass(frozen=True)
class RulesResult:
    action: str
    rules: list[RuleFile]


def load_delivery_rules(project_root: Path, action: str) -> RulesResult:
    project_root = project_root.resolve()
    if not is_unity_project(project_root):
        raise DeliveryError(
            code="NOT_UNITY_PROJECT",
            message=f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {project_root}",
            exit_code=1,
        )
    if not action or action.strip() != action or "/" in action or "\\" in action or ".." in action:
        raise DeliveryError(code="INVALID_ACTION", message="action 不合法", exit_code=2)

    repo_root = package_root()
    rule_path = repo_root / "pack" / "skills" / "delivery" / "references" / f"{action}.md"
    if not rule_path.is_file():
        raise DeliveryError(code="UNKNOWN_ACTION", message=f"未知动作: {action}", exit_code=1)
    if rule_path.is_symlink():
        raise DeliveryError(code="SYMLINK", message="规则文件不能是符号链接", exit_code=1)

    raw = rule_path.read_bytes()
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DeliveryError(code="INVALID_ENCODING", message="规则文件必须是 UTF-8", exit_code=1) from error

    digest = hashlib.sha256(raw).hexdigest()
    rel = rule_path.relative_to(repo_root).as_posix()
    return RulesResult(
        action=action,
        rules=[RuleFile(path=rel, sha256=f"sha256:{digest}", body=body)],
    )
