"""独游模式的框架基线：Agent 写，这里只做确定性的解析、校验和体检。

位置和作用与 ``tasks.py`` 一致：Agent 产出 ``framework.json``，工作流负责判断它
能不能作为后续切片的地基，并把扩展点压成提示词能用的短文本。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

FrameworkStatus = Literal["draft", "done"]
SystemStatus = Literal["pending", "done"]
FRAMEWORK_STATUSES = {"draft", "done"}
SYSTEM_STATUSES = {"pending", "done"}
NEW_HOOK_PREFIX = "new:"


@dataclass
class FrameworkSystem:
    id: str
    title: str
    paths: list[str]
    status: SystemStatus
    notes: str | None = None


@dataclass
class ExtensionPoint:
    name: str
    how_to: str
    path: str | None = None


@dataclass
class FrameworkPlan:
    game: str
    paradigm: str
    root: str
    systems: list[FrameworkSystem]
    status: FrameworkStatus
    assemblies: list[str] = field(default_factory=list)
    extension_points: list[ExtensionPoint] = field(default_factory=list)
    conventions: list[str] = field(default_factory=list)


def parse_framework_plan(data: object) -> FrameworkPlan | None:
    root = _as_object(data)
    if root is None:
        return None
    if not _non_empty(root.get("game")) or not _non_empty(root.get("paradigm")) or not _non_empty(root.get("root")):
        return None
    if not _is_relative_path(root["root"]):
        return None
    status = root.get("status")
    if not isinstance(status, str) or status not in FRAMEWORK_STATUSES:
        return None
    if not _is_optional_string_array(root.get("assemblies")):
        return None
    if not _is_optional_string_array(root.get("conventions")):
        return None

    systems = _parse_systems(root.get("systems"))
    if systems is None:
        return None
    extension_points = _parse_extension_points(root.get("extensionPoints"))
    if extension_points is None:
        return None

    return FrameworkPlan(
        game=root["game"],
        paradigm=root["paradigm"],
        root=root["root"],
        systems=systems,
        status=status,  # type: ignore[arg-type]
        assemblies=_as_string_list(root.get("assemblies")),
        extension_points=extension_points,
        conventions=_as_string_list(root.get("conventions")),
    )


def read_framework_plan(file_path: str | Path) -> FrameworkPlan | None:
    try:
        text = Path(file_path).read_text(encoding="utf-8")
        return parse_framework_plan(json.loads(text))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def framework_ready(plan: FrameworkPlan | None) -> bool:
    """框架阶段结束的判定：状态是 done，且至少有一个系统已经落地。"""
    if plan is None or plan.status != "done":
        return False
    return any(system.status == "done" for system in plan.systems)


def framework_path_findings(
    plan: FrameworkPlan,
    project_root: str | os.PathLike[str],
    framework_doc_path: str = "",
) -> list[str]:
    """框架的软检查：只提示，不阻断。返回给终端看的问题列表。

    和 ``framework_drift`` 的区别：这里额外看代码根目录、扩展点是否覆盖四类、
    框架文档有没有真的写出来。
    """
    root = Path(project_root)
    findings: list[str] = []

    code_root = plan.root.strip()
    if code_root and not (root / code_root.replace("\\", "/")).exists():
        findings.append(f"代码根目录不存在：{code_root}")

    for item in framework_drift(plan, project_root):
        findings.append(f"登记的文件在磁盘上找不到：{item}")

    if not plan.extension_points:
        findings.append("extensionPoints 是空的：至少写清怎么加新状态、新事件、新配置、新存档字段")
    else:
        covered = {_hook_kind(point.how_to) for point in plan.extension_points}
        missing = [title for kind, title in HOOK_KINDS.items() if kind not in covered]
        if missing:
            findings.append("扩展点没覆盖这几类：" + "、".join(missing))

    if framework_doc_path:
        doc = Path(framework_doc_path)
        if not doc.is_file() or doc.stat().st_size == 0:
            findings.append(f"框架文档没有写出来：{framework_doc_path}（写一份或把 indie.framework.docEnabled 设为 false）")
        elif _looks_like_a_template(doc.read_text(encoding="utf-8", errors="replace")):
            findings.append(f"框架文档还是模板骨架：{framework_doc_path}（把占位符和空章节填掉）")

    return findings


def framework_doc_problems(plan: FrameworkPlan, framework_doc_path: str) -> list[str]:
    """框架文档的硬检查：文档路径配了就必须写出来。"""
    if not framework_doc_path:
        return []
    doc = Path(framework_doc_path)
    if not doc.is_file() or doc.stat().st_size == 0:
        return [f"框架文档没有写出来：{framework_doc_path}"]
    if _looks_like_a_template(doc.read_text(encoding="utf-8", errors="replace")):
        return [f"框架文档还是模板骨架（占位符没替换）：{framework_doc_path}"]
    return []


HOOK_KINDS = {
    "state": "新状态",
    "event": "新事件",
    "config": "新配置",
    "save": "新存档字段",
}
_HOOK_KEYWORDS = {
    "state": ("状态", "state", "State"),
    "event": ("事件", "Event", "event"),
    "config": ("配置", "Config", "config", "SO", "ScriptableObject"),
    "save": ("存档", "Save", "save"),
}
_TEMPLATE_MARKERS = ("{game}", "{游戏名}", "{game} 的游戏")


def _hook_kind(how_to: str) -> str:
    for kind, keywords in _HOOK_KEYWORDS.items():
        if any(word in how_to for word in keywords):
            return kind
    return ""


def _looks_like_a_template(text: str) -> bool:
    """没替换占位符，或只有骨架标题没有正文。"""
    if any(marker in text for marker in _TEMPLATE_MARKERS):
        return True
    stripped = [line.strip() for line in text.splitlines() if line.strip()]
    if len(stripped) <= 3:
        return True
    return False


def known_hooks(plan: FrameworkPlan) -> set[str]:
    """切片可以引用的挂载点：系统 id 与扩展点名。"""
    hooks = {system.id for system in plan.systems}
    hooks.update(point.name for point in plan.extension_points)
    return hooks


def framework_drift(plan: FrameworkPlan, project_root: str | os.PathLike[str]) -> list[str]:
    """登记过、但磁盘上已经找不到的路径。只用于提示，不阻塞。"""
    root = Path(project_root)
    missing: list[str] = []
    recorded: list[str] = []
    for system in plan.systems:
        recorded.extend(system.paths)
    for point in plan.extension_points:
        if point.path:
            recorded.append(point.path)
    seen: set[str] = set()
    for item in recorded:
        normalized = item.replace("\\", "/")
        if normalized in seen:
            continue
        seen.add(normalized)
        if not (root / normalized).exists():
            missing.append(normalized)
    return missing


def plan_summary(plan: FrameworkPlan) -> str:
    """把框架压成几行，供分析/实现阶段的提示词使用。"""
    lines = [
        f"框架范式：{plan.paradigm}",
        f"代码根目录：{plan.root}",
    ]
    if plan.assemblies:
        lines.append(f"程序集：{'、'.join(plan.assemblies)}")
    systems = "、".join(f"{system.id}（{system.title}）" for system in plan.systems)
    lines.append(f"核心系统：{systems}")
    if plan.extension_points:
        lines.append(
            "扩展点：" + "、".join(f"{point.name}（{point.how_to}）" for point in plan.extension_points)
        )
    if plan.conventions:
        lines.append("约定：" + "；".join(plan.conventions))
    return "\n".join(lines)


def task_framework_brief(plan: FrameworkPlan, hooks: list[str], framework_doc_path: str = "") -> str:
    """实现阶段只需要本任务引用的挂载点和约定，不必带整份框架清单。"""
    wanted = [hook.strip() for hook in hooks if hook.strip()]
    lines = [f"框架范式：{plan.paradigm}", f"代码根目录：{plan.root}"]
    known = {system.id: system for system in plan.systems}
    points = {point.name: point for point in plan.extension_points}
    picked: list[str] = []
    for hook in wanted:
        if hook in known:
            system = known[hook]
            picked.append(f"{hook}（{system.title}）")
        elif hook in points:
            point = points[hook]
            picked.append(f"{hook}（{point.how_to}）")
        elif hook.startswith(NEW_HOOK_PREFIX):
            picked.append(hook)
    if picked:
        lines.append("本任务挂载：")
        lines.extend(f"- {item}" for item in picked)
    if plan.conventions:
        lines.append("约定：" + "；".join(plan.conventions))
    if framework_doc_path:
        lines.append(f"框架文档：{framework_doc_path}")
    return "\n".join(lines)


def hook_aliases(plan: FrameworkPlan) -> str:
    """提示词里给 Agent 看的挂载点清单。"""
    aliases = sorted(known_hooks(plan))
    return "、".join(aliases) if aliases else "（框架没有登记扩展点）"


def _parse_systems(value: object) -> list[FrameworkSystem] | None:
    if not isinstance(value, list) or len(value) == 0:
        return None
    systems: list[FrameworkSystem] = []
    ids: set[str] = set()
    for item in value:
        system = _parse_system(item)
        if system is None or system.id in ids:
            return None
        ids.add(system.id)
        systems.append(system)
    return systems


def _parse_system(value: object) -> FrameworkSystem | None:
    root = _as_object(value)
    if root is None:
        return None
    if not _non_empty(root.get("id")) or not _non_empty(root.get("title")):
        return None
    status = root.get("status")
    if not isinstance(status, str) or status not in SYSTEM_STATUSES:
        return None
    if not _is_optional_string_array(root.get("paths")):
        return None
    if not all(_is_relative_path(item) for item in _as_string_list(root.get("paths"))):
        return None
    notes = root.get("notes")
    if notes is not None and not isinstance(notes, str):
        return None
    system = FrameworkSystem(
        id=root["id"],
        title=root["title"],
        paths=_as_string_list(root.get("paths")),
        status=status,  # type: ignore[arg-type]
    )
    if isinstance(notes, str) and notes.strip() != "":
        system.notes = notes
    return system


def _parse_extension_points(value: object) -> list[ExtensionPoint] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    points: list[ExtensionPoint] = []
    names: set[str] = set()
    for item in value:
        root = _as_object(item)
        if root is None:
            return None
        if not _non_empty(root.get("name")) or not _non_empty(root.get("howTo")):
            return None
        name = root["name"]
        if name in names:
            return None
        names.add(name)
        path = root.get("path")
        if path is not None and not isinstance(path, str):
            return None
        if isinstance(path, str) and path.strip() != "" and not _is_relative_path(path):
            return None
        point = ExtensionPoint(name=name, how_to=root["howTo"])
        if isinstance(path, str) and path.strip() != "":
            point.path = path
        points.append(point)
    return points


def _as_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_string_array(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_optional_string_array(value: object) -> bool:
    return value is None or _is_string_array(value)


def _as_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _is_relative_path(value: object) -> bool:
    """framework.json 里的路径一律相对工程根：绝对路径说明写错了。"""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text.startswith(("/", "\\")):
        return False
    if len(text) > 2 and text[1] == ":" and text[2] in ("/", "\\"):
        return False
    return ".." not in text.split("/")
