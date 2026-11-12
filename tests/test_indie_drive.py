from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bulings.config import ProjectProfile
from bulings.runner import ResumeCommand, RunState, _drive, _save_state, resume_workflow


class FakeRun:
    def __init__(self, run_id: str) -> None:
        self.id = run_id

    def supports(self, name: str) -> bool:
        return False

    def messages(self):  # pragma: no cover - 只在 supports 为真时用到
        return iter(())

    def wait(self) -> SimpleNamespace:
        return SimpleNamespace(status="finished", id=self.id, result="")


class FakeAgent:
    """把每次 send 记下来，并按提示词阶段调用对应的副作用。"""

    def __init__(self, on_send=None) -> None:
        self.agent_id = "agent-1"
        self.prompts: list[str] = []
        self._on_send = on_send

    def send(self, prompt: str) -> FakeRun:
        self.prompts.append(prompt)
        if self._on_send is not None:
            self._on_send(prompt, self.prompts)
        return FakeRun(f"run-{len(self.prompts)}")

    def stages(self) -> list[str]:
        found = []
        for prompt in self.prompts:
            if "「建立框架」阶段" in prompt:
                found.append("framework")
            elif "「拆切片」阶段" in prompt:
                found.append("analyze")
            elif "「实现一个切片」阶段" in prompt:
                found.append("implement")
            elif "「功能说明」阶段" in prompt:
                found.append("document")
            else:
                found.append("unknown")
        return found


def _unity_project(root: Path, mode: str = "indie") -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()
    (root / ".bulings").mkdir(parents=True, exist_ok=True)
    (root / ".bulings" / "workflow.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")


def _plan_payload(status: str = "done") -> dict:
    return {
        "game": "game",
        "paradigm": "轻量自建",
        "root": "Assets/_Game",
        "systems": [{"id": "bootstrap", "title": "启动", "paths": [], "status": "done"}],
        "extensionPoints": [{"name": "EventBus", "howTo": "Send/Subscribe"}],
        "conventions": ["功能放 Features/"],
        "status": status,
    }


def _tasks_payload(status: str = "pending", hooks: list[str] | None = None) -> dict:
    return {
        "feature": "demo",
        "designDoc": "design.md",
        "prefabs": [],
        "tasks": [
            {
                "id": "T1",
                "title": "放置炮塔",
                "slice": "放置炮塔",
                "goal": "把炮塔放到格子上",
                "dependsOn": [],
                "files": ["Assets/_Game/Features/Tower/TowerPlacer.cs"],
                "prefabNodes": [],
                "framework": ["EventBus"] if hooks is None else hooks,
                "acceptance": ["能放下并看到"],
                "status": status,
            }
        ],
    }


def _write_plan(root: Path, status: str = "done") -> Path:
    path = root / ".bulings" / "indie" / "framework.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plan_payload(status), ensure_ascii=False), encoding="utf-8")
    return path


def _write_tasks(root: Path, status: str = "pending", hooks: list[str] | None = None) -> Path:
    path = root / ".bulings" / "runs" / "demo" / "tasks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_tasks_payload(status, hooks), ensure_ascii=False), encoding="utf-8")
    return path


def _state(root: Path, **overrides) -> RunState:
    state = RunState(
        slug="demo",
        feature="demo",
        design_path=str(root / "design.md"),
        prefabs=[],
        dev_spec_enabled=True,
        feature_doc_enabled=True,
        dev_spec_path=str(root / "Docs" / "AI" / "DevSpecs" / "demo.md"),
        feature_doc_path=str(root / "Docs" / "AI" / "Features" / "demo.md"),
        model="composer-2.5",
        phase="analyze",
        mode="indie",
        game="game",
        framework_enabled=True,
        framework_plan_path=str(root / ".bulings" / "indie" / "framework.json"),
        framework_doc_path=str(root / "Docs" / "AI" / "Frameworks" / "game.md"),
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _side_effects(root: Path, outcome: dict) -> None:
    """按阶段写产物，模拟 Agent 的落盘行为。"""

    def on_send(prompt: str, prompts: list[str]) -> None:
        if "「建立框架」阶段" in prompt:
            outcome["framework"] = _write_plan(root, outcome.get("framework_status", "done"))
        elif "「拆切片」阶段" in prompt:
            outcome["tasks"] = _write_tasks(root, hooks=outcome.get("hooks"))
        elif "「实现一个切片」阶段" in prompt and "T1" in prompt:
            outcome["tasks"] = _write_tasks(root, status="done", hooks=outcome.get("hooks"))
        elif "「功能说明」阶段" in prompt:
            doc = root / "Docs" / "AI" / "Features" / "demo.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text("# demo\n", encoding="utf-8")
            outcome["document"] = doc

    return on_send


def test_indie_run_builds_the_framework_before_any_slice(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent(_side_effects(tmp_path, {}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 0
    assert agent.stages() == ["framework", "analyze", "implement", "document"]
    assert state.phase == "done"
    assert (tmp_path / ".bulings" / "indie" / "framework.json").is_file()


def test_indie_stops_when_the_framework_is_not_ready(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent(_side_effects(tmp_path, {"framework_status": "draft"}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 2
    assert agent.stages() == ["framework"]
    assert state.phase == "framework"
    assert not (tmp_path / ".bulings" / "runs" / "demo" / "tasks.json").exists()


def test_indie_skips_the_framework_when_it_is_already_ready(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    _write_plan(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent(_side_effects(tmp_path, {}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 0
    assert agent.stages() == ["analyze", "implement", "document"]


def test_indie_rejects_slices_that_are_not_on_the_framework(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    _write_plan(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent(_side_effects(tmp_path, {"hooks": ["NoSuchSystem"]}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 2
    assert agent.stages() == ["analyze"]
    assert state.phase == "analyze"


def test_indie_without_framework_only_asks_for_declared_hooks(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    state = _state(tmp_path, framework_enabled=False)
    agent = FakeAgent(_side_effects(tmp_path, {"hooks": ["new: 格子坐标服务"]}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 0
    assert agent.stages() == ["analyze", "implement", "document"]
    assert not (tmp_path / ".bulings" / "indie" / "framework.json").exists()


def test_indie_interrupted_framework_phase_resumes_with_the_draft(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    _write_plan(tmp_path, status="draft")
    state = _state(tmp_path, phase="framework")
    agent = FakeAgent(_side_effects(tmp_path, {}))

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), True)

    assert code == 0
    assert agent.stages() == ["framework", "analyze", "implement", "document"]
    assert "不要重建已经落地的系统" in agent.prompts[0]


def test_state_round_trip_keeps_mode_and_framework_paths(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    state = _state(tmp_path)
    _save_state(str(tmp_path), state)

    from bulings.runner import _read_state, _state_path

    loaded = _read_state(_state_path(str(tmp_path), "demo"))
    assert loaded is not None
    assert loaded.mode == "indie"
    assert loaded.framework_enabled is True
    assert loaded.framework_plan_path == state.framework_plan_path
    assert loaded.game == "game"


def test_legacy_state_without_mode_is_read_as_work(tmp_path: Path) -> None:
    _unity_project(tmp_path)
    path = tmp_path / ".bulings" / "runs" / "demo" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"slug": "demo", "feature": "demo", "phase": "analyze", "agentId": "agent-1"}),
        encoding="utf-8",
    )

    from bulings.runner import _read_state, _state_path

    loaded = _read_state(_state_path(str(tmp_path), "demo"))
    assert loaded is not None
    assert loaded.mode == "work"
    assert loaded.framework_enabled is False


def test_resume_refuses_a_run_from_another_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _unity_project(tmp_path, mode="work")
    _save_state(str(tmp_path), _state(tmp_path, phase="analyze", agent_id="agent-1"))

    code = resume_workflow(ResumeCommand(project=str(tmp_path), slug="demo"))

    assert code == 1
    assert "indie" in capsys.readouterr().err
