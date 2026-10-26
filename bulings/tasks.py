from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

TaskStatus = Literal["pending", "in_progress", "done", "blocked"]
NextKind = Literal["task", "blocked", "waiting", "done"]
STATUSES = {"pending", "in_progress", "done", "blocked"}


@dataclass
class FeatureTask:
    id: str
    title: str
    goal: str
    depends_on: list[str]
    files: list[str]
    prefab_nodes: list[str]
    acceptance: list[str]
    status: TaskStatus
    blocked_reason: str | None = None


@dataclass
class TaskFile:
    feature: str
    design_doc: str
    prefabs: list[str]
    tasks: list[FeatureTask]


@dataclass(frozen=True)
class NextTask:
    kind: NextKind
    task: FeatureTask | None = None
    retry: bool = False


def parse_task_file(data: object) -> TaskFile | None:
    root = _as_object(data)
    if root is None:
        return None
    if not _non_empty(root.get("feature")) or not isinstance(root.get("designDoc"), str):
        return None
    if not _is_string_array(root.get("prefabs")):
        return None
    raw_tasks = root.get("tasks")
    if not isinstance(raw_tasks, list) or len(raw_tasks) == 0:
        return None

    tasks: list[FeatureTask] = []
    ids: set[str] = set()
    for item in raw_tasks:
        task = _parse_task(item)
        if task is None or task.id in ids:
            return None
        ids.add(task.id)
        tasks.append(task)

    return TaskFile(
        feature=root["feature"],
        design_doc=root["designDoc"],
        prefabs=list(root["prefabs"]),
        tasks=tasks,
    )


def read_task_file(file_path: str | Path) -> TaskFile | None:
    try:
        text = Path(file_path).read_text(encoding="utf-8")
        return parse_task_file(json.loads(text))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def write_task_file(file_path: str | Path, task_file: TaskFile) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "feature": task_file.feature,
        "designDoc": task_file.design_doc,
        "prefabs": list(task_file.prefabs),
        "tasks": [_task_to_dict(task) for task in task_file.tasks],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def select_next_task(tasks: list[FeatureTask]) -> NextTask:
    in_progress = next((task for task in tasks if task.status == "in_progress"), None)
    if in_progress is not None:
        return NextTask(kind="task", task=in_progress, retry=True)

    done = {task.id for task in tasks if task.status == "done"}
    pending = [task for task in tasks if task.status == "pending"]
    runnable = next((task for task in pending if all(dep in done for dep in task.depends_on)), None)
    if runnable is not None:
        return NextTask(kind="task", task=runnable, retry=False)

    blocked = next((task for task in tasks if task.status == "blocked"), None)
    if blocked is not None:
        return NextTask(kind="blocked", task=blocked)

    if pending:
        return NextTask(kind="waiting", task=pending[0])
    return NextTask(kind="done")


def mark_task_in_progress(task_file: TaskFile, task_id: str) -> TaskFile:
    tasks: list[FeatureTask] = []
    for task in task_file.tasks:
        if task.id == task_id and task.status == "pending":
            tasks.append(_replace_status(task, "in_progress"))
        else:
            tasks.append(task)
    return TaskFile(
        feature=task_file.feature,
        design_doc=task_file.design_doc,
        prefabs=list(task_file.prefabs),
        tasks=tasks,
    )


def reopen_blocked_task(task_file: TaskFile, task_id: str | None) -> TaskFile | None:
    if not task_id:
        return None
    current = next((task for task in task_file.tasks if task.id == task_id), None)
    if current is None or current.status != "blocked":
        return None
    return TaskFile(
        feature=task_file.feature,
        design_doc=task_file.design_doc,
        prefabs=list(task_file.prefabs),
        tasks=[_replace_status(task, "in_progress") if task.id == current.id else task for task in task_file.tasks],
    )


def _replace_status(task: FeatureTask, status: TaskStatus) -> FeatureTask:
    return FeatureTask(
        id=task.id,
        title=task.title,
        goal=task.goal,
        depends_on=list(task.depends_on),
        files=list(task.files),
        prefab_nodes=list(task.prefab_nodes),
        acceptance=list(task.acceptance),
        status=status,
        blocked_reason=task.blocked_reason,
    )


def _task_to_dict(task: FeatureTask) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "goal": task.goal,
        "dependsOn": list(task.depends_on),
        "files": list(task.files),
        "prefabNodes": list(task.prefab_nodes),
        "acceptance": list(task.acceptance),
        "status": task.status,
    }
    if task.blocked_reason:
        data["blockedReason"] = task.blocked_reason
    return data


def _parse_task(value: object) -> FeatureTask | None:
    root = _as_object(value)
    if root is None:
        return None
    if not _non_empty(root.get("id")) or not _non_empty(root.get("title")) or not _non_empty(root.get("goal")):
        return None
    status = root.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return None
    if not _is_optional_string_array(root.get("dependsOn")):
        return None
    if not _is_optional_string_array(root.get("files")):
        return None
    if not _is_optional_string_array(root.get("prefabNodes")):
        return None
    if not _is_optional_string_array(root.get("acceptance")):
        return None
    blocked_reason = root.get("blockedReason")
    if blocked_reason is not None and not isinstance(blocked_reason, str):
        return None

    task = FeatureTask(
        id=root["id"],
        title=root["title"],
        goal=root["goal"],
        depends_on=_as_string_list(root.get("dependsOn")),
        files=_as_string_list(root.get("files")),
        prefab_nodes=_as_string_list(root.get("prefabNodes")),
        acceptance=_as_string_list(root.get("acceptance")),
        status=status,  # type: ignore[arg-type]
    )
    if isinstance(blocked_reason, str) and blocked_reason.strip() != "":
        task.blocked_reason = blocked_reason
    return task


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
