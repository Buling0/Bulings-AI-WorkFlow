"""改动范围审计：看工作区改了什么，报三种风险。

提示词反复要求「不改 protectedPaths、不动 .meta」，但没人验证。这里用 git 的
工作区状态做一次只读检查，不碰文件内容，也不建 commit。

分三级：error（命中受保护路径，必须处理）、warn（动了 .meta，可能是 Unity 自动改）、
info（改动落在配置的 codeRoots 之外，只提示）。
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from bulings.delivery.git_util import is_git_repo

LEVEL_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclass
class AuditFinding:
    level: str
    path: str
    message: str


@dataclass
class AuditReport:
    is_git: bool
    changed: list[str] = field(default_factory=list)
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[AuditFinding]:
        return [item for item in self.findings if item.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def lines(self) -> list[str]:
        if not self.is_git:
            return ["不是 git 仓库，无法审计工作区改动（跳过）。"]
        if not self.changed:
            return ["工作区没有改动。"]
        lines = [f"审计了 {len(self.changed)} 个改动文件。"]
        for finding in sorted(self.findings, key=lambda item: (LEVEL_ORDER.get(item.level, 9), item.path)):
            lines.append(f"[{finding.level.upper()}] {finding.path}：{finding.message}")
        if not self.findings:
            lines.append("没有命中受保护路径、.meta 或 codeRoots 之外的文件。")
        return lines


def audit_workspace(
    project_root: str | os.PathLike[str],
    protected_paths: list[str] | None = None,
    code_roots: list[str] | None = None,
) -> AuditReport:
    root = Path(project_root)
    if not is_git_repo(root):
        return AuditReport(is_git=False)
    changed = sorted(_changed_files(root))
    findings: list[AuditFinding] = []
    protected = [_normalize(item) for item in protected_paths or [] if item.strip()]
    roots = [_normalize(item) for item in code_roots or [] if item.strip()]
    for path in changed:
        normalized = _normalize(path)
        if _under_any(normalized, protected):
            findings.append(AuditFinding("error", normalized, "改动了 protectedPaths 里的路径"))
            continue
        if normalized.endswith(".meta"):
            findings.append(AuditFinding("warn", normalized, "改动了 .meta（确认不是 guid 变化）"))
            continue
        if roots and not _under_any(normalized, roots) and not normalized.startswith((".bulings/", "Docs/AI/")):
            findings.append(AuditFinding("info", normalized, "改动落在 codeRoots 之外"))
    return AuditReport(is_git=True, changed=changed, findings=findings)


def _changed_files(root: Path) -> list[str]:
    """``--untracked-files=all`` 把新目录展开成文件，否则只能看到一个目录名。"""
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
    )
    if result.returncode != 0:
        return []
    raw = result.stdout.decode("utf-8", errors="replace")
    paths: list[str] = []
    parts = raw.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if status.startswith("R") and index < len(parts):
            path = parts[index]
            index += 1
        paths.append(path.replace("\\", "/"))
    return paths


def format_audit_errors(report: AuditReport) -> list[str]:
    """运行期只报错误级，免得把已有的无关改动也打出来。"""
    return [f"[审计] {item.path}：{item.message}" for item in report.errors]


def _normalize(value: str) -> str:
    text = value.strip().replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _under_any(path: str, prefixes: list[str]) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in prefixes)
