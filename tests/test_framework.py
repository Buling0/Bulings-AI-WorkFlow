import json
import tempfile
from pathlib import Path

from bulings.framework import (
    framework_drift,
    framework_ready,
    hook_aliases,
    known_hooks,
    parse_framework_plan,
    plan_summary,
    read_framework_plan,
)


def _system(system_id: str = "bootstrap", status: str = "done", **extra) -> dict:
    return {
        "id": system_id,
        "title": "启动与生命周期",
        "paths": ["Assets/_Game/Core/Bootstrap"],
        "status": status,
        **extra,
    }


def _point(name: str = "EventBus") -> dict:
    return {"name": name, "howTo": "定义 GameEvent 子类后 Send/Subscribe"}


def _plan(**overrides) -> dict:
    payload = {
        "game": "tower-defense",
        "paradigm": "轻量自建",
        "root": "Assets/_Game",
        "assemblies": ["Game.Core"],
        "systems": [_system()],
        "extensionPoints": [_point()],
        "conventions": ["功能代码放 Assets/_Game/Features/"],
        "status": "done",
    }
    payload.update(overrides)
    return payload


def test_parses_a_complete_plan() -> None:
    plan = parse_framework_plan(_plan())
    assert plan is not None
    assert plan.game == "tower-defense"
    assert plan.root == "Assets/_Game"
    assert [system.id for system in plan.systems] == ["bootstrap"]
    assert plan.extension_points[0].name == "EventBus"
    assert plan.status == "done"


def test_optional_sections_may_be_missing() -> None:
    payload = _plan()
    for key in ("assemblies", "extensionPoints", "conventions"):
        payload.pop(key)
    plan = parse_framework_plan(payload)
    assert plan is not None
    assert plan.assemblies == []
    assert plan.extension_points == []
    assert plan.conventions == []


def test_rejects_missing_required_fields() -> None:
    for key in ("game", "paradigm", "root", "status"):
        payload = _plan()
        payload.pop(key)
        assert parse_framework_plan(payload) is None, key
    assert parse_framework_plan(_plan(game="  ")) is None
    assert parse_framework_plan(_plan(status="later")) is None
    assert parse_framework_plan([_plan()]) is None


def test_rejects_broken_systems() -> None:
    assert parse_framework_plan(_plan(systems=[])) is None
    assert parse_framework_plan(_plan(systems=[_system(status="doing")])) is None
    assert parse_framework_plan(_plan(systems=[_system(id="  ")])) is None
    assert parse_framework_plan(_plan(systems=[_system(), _system()])) is None
    broken = _system()
    broken.pop("title")
    assert parse_framework_plan(_plan(systems=[broken])) is None
    assert parse_framework_plan(_plan(systems=[_system(paths="not-a-list")])) is None
    assert parse_framework_plan(_plan(systems=[_system(notes=5)])) is None


def test_rejects_broken_extension_points() -> None:
    assert parse_framework_plan(_plan(extensionPoints=[{"name": "EventBus"}])) is None
    assert parse_framework_plan(_plan(extensionPoints=[_point(), _point()])) is None
    assert parse_framework_plan(_plan(extensionPoints="EventBus")) is None


def test_ready_requires_done_status_and_one_landed_system() -> None:
    assert framework_ready(None) is False
    assert framework_ready(parse_framework_plan(_plan(status="draft"))) is False
    pending_only = parse_framework_plan(_plan(systems=[_system(status="pending")]))
    assert framework_ready(pending_only) is False
    assert framework_ready(parse_framework_plan(_plan())) is True


def test_known_hooks_merges_systems_and_extension_points() -> None:
    plan = parse_framework_plan(
        _plan(systems=[_system("state"), _system("events")], extensionPoints=[_point("EventBus"), _point("Save")])
    )
    assert plan is not None
    assert known_hooks(plan) == {"state", "events", "EventBus", "Save"}
    assert "EventBus" in hook_aliases(plan)


def test_drift_lists_recorded_paths_missing_on_disk() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-framework-") as directory:
        root = Path(directory)
        plan = parse_framework_plan(
            _plan(
                systems=[_system("bootstrap", paths=["Assets/_Game/Core/Bootstrap", "Assets/_Game/Core/Missing"])],
                extensionPoints=[{"name": "Save", "howTo": "加字段", "path": "Assets/_Game/Core/Save"}],
            )
        )
        assert plan is not None
        (root / "Assets" / "_Game" / "Core" / "Bootstrap").mkdir(parents=True)
        drift = framework_drift(plan, root)
        assert drift == ["Assets/_Game/Core/Missing", "Assets/_Game/Core/Save"]
        (root / "Assets" / "_Game" / "Core" / "Missing").mkdir()
        (root / "Assets" / "_Game" / "Core" / "Save").mkdir()
        assert framework_drift(plan, root) == []


def test_read_plan_returns_none_for_missing_or_invalid_files() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-framework-") as directory:
        root = Path(directory)
        assert read_framework_plan(root / "nope.json") is None
        broken = root / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        assert read_framework_plan(broken) is None
        good = root / "framework.json"
        good.write_text(json.dumps(_plan(), ensure_ascii=False), encoding="utf-8")
        assert read_framework_plan(good) is not None


def test_plan_summary_mentions_hooks_and_conventions() -> None:
    plan = parse_framework_plan(_plan())
    assert plan is not None
    summary = plan_summary(plan)
    assert "轻量自建" in summary
    assert "bootstrap" in summary
    assert "EventBus" in summary
    assert "Assets/_Game/Features/" in summary
