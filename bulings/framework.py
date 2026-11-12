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
