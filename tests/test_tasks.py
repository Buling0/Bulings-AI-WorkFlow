from bulings.tasks import FeatureTask, parse_task_file, reopen_blocked_task, select_next_task


def _task(task_id: str, status: str, depends_on: list[str] | None = None, blocked_reason: str | None = None) -> FeatureTask:
    return FeatureTask(
        id=task_id,
        title=task_id,
        goal=task_id,
        depends_on=depends_on or [],
        files=[],
        prefab_nodes=[],
        acceptance=[],
        status=status,  # type: ignore[arg-type]
        blocked_reason=blocked_reason,
    )


def _raw(task_id: str, status: str, depends_on: list[str] | None = None) -> dict:
    return {
        "id": task_id,
        "title": task_id,
        "goal": task_id,
        "dependsOn": depends_on or [],
        "files": [],
        "prefabNodes": [],
        "acceptance": [],
        "status": status,
    }


def _file(tasks: list[dict]) -> dict:
    return {"feature": "背包", "designDoc": "design.md", "prefabs": ["Bag.prefab"], "tasks": tasks}


def test_picks_task_whose_dependencies_are_met() -> None:
    nxt = select_next_task(
        [
            _task("T1", "pending", ["T2"]),
            _task("T2", "pending"),
        ]
    )
    assert nxt.kind == "task"
    assert nxt.task is not None
    assert nxt.task.id == "T2"
    assert nxt.retry is False


def test_does_not_skip_to_a_dependent_task() -> None:
    nxt = select_next_task(
        [
            _task("T1", "pending"),
            _task("T2", "pending", ["T1"]),
        ]
    )
    assert nxt.kind == "task"
    assert nxt.task is not None
    assert nxt.task.id == "T1"


def test_stops_on_blocked_when_nothing_else_can_run() -> None:
    nxt = select_next_task(
        [
            _task("T1", "blocked", blocked_reason="预制体缺少关闭按钮"),
            _task("T2", "done"),
        ]
    )
    assert nxt.kind == "blocked"
    assert nxt.task is not None
    assert nxt.task.id == "T1"


def test_runs_tasks_that_do_not_depend_on_blocked_work() -> None:
    nxt = select_next_task(
        [
            _task("T1", "blocked", blocked_reason="预制体缺少关闭按钮"),
            _task("T2", "pending"),
        ]
    )
    assert nxt.kind == "task"
    assert nxt.task is not None
    assert nxt.task.id == "T2"


def test_in_progress_is_retried() -> None:
    nxt = select_next_task(
        [
            _task("T1", "done"),
            _task("T2", "in_progress", ["T1"]),
            _task("T3", "pending", ["T2"]),
        ]
    )
    assert nxt.kind == "task"
    assert nxt.task is not None
    assert nxt.task.id == "T2"
    assert nxt.retry is True


def test_mutual_dependencies_wait() -> None:
    nxt = select_next_task(
        [
            _task("T1", "pending", ["T2"]),
            _task("T2", "pending", ["T1"]),
        ]
    )
    assert nxt.kind == "waiting"
    assert nxt.task is not None
    assert nxt.task.id == "T1"


def test_done_when_every_task_is_done() -> None:
    assert select_next_task([_task("T1", "done")]).kind == "done"


def test_tasks_json_rejects_duplicate_ids_and_unknown_status() -> None:
    assert parse_task_file(_file([_raw("T1", "pending"), _raw("T1", "pending")])) is None
    payload = _file([_raw("T1", "pending")])
    payload["tasks"] = [
        {
            "id": "T1",
            "title": "a",
            "goal": "b",
            "dependsOn": [],
            "files": [],
            "prefabNodes": [],
            "acceptance": [],
            "status": "later",
        }
    ]
    assert parse_task_file(payload) is None


def test_resume_reopens_only_the_current_blocked_task() -> None:
    parsed = parse_task_file(
        _file(
            [
                {**_raw("T1", "blocked"), "blockedReason": "缺按钮"},
                {**_raw("T2", "blocked"), "blockedReason": "别的原因"},
                _raw("T3", "done"),
            ]
        )
    )
    assert parsed is not None
    updated = reopen_blocked_task(parsed, "T1")
    assert updated is not None
    statuses = {task.id: task.status for task in updated.tasks}
    assert statuses == {"T1": "in_progress", "T2": "blocked", "T3": "done"}
    assert updated.tasks[0].blocked_reason == "缺按钮"
    assert reopen_blocked_task(parsed, "T3") is None
