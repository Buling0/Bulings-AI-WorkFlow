from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bulings import runner
from bulings.config import ProjectProfile
from bulings.flowchart import (
    DRAFT_MARKER,
    confirm_flow_file,
    confirm_flow_markdown,
    flow_file_path,
    flow_problems,
    flow_ready_for_gate,
    flow_template,
    is_confirmed,
)
from bulings.prompts import PromptContext, analyze_prompt, implement_prompt
from bulings.runner import RunState, _drive
from bulings.tasks import FeatureTask


class FakeRun:
    def __init__(self, run_id: str) -> None:
        self.id = run_id

    def supports(self, name: str) -> bool:
        return False

    def messages(self):  # pragma: no cover
        return iter(())

    def wait(self) -> SimpleNamespace:
        return SimpleNamespace(status="finished", id=self.id, result="")


class FakeAgent:
    def __init__(self) -> None:
        self.agent_id = "agent-1"
        self.prompts: list[str] = []
        self.on_send = None

    def send(self, prompt: str) -> FakeRun:
        self.prompts.append(prompt)
        if self.on_send is not None:
            self.on_send(prompt)
        return FakeRun(f"run-{len(self.prompts)}")


def _project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()
    (root / ".bulings").mkdir(parents=True, exist_ok=True)
    (root / ".bulings" / "workflow.yaml").write_text("mode: work\n", encoding="utf-8")
    (root / "design.md").write_text("# 背包\n", encoding="utf-8")


def _state(root: Path, **overrides) -> RunState:
    state = RunState(
        slug="bag",
        feature="bag",
        design_path=str(root / "design.md"),
        prefabs=[],
        dev_spec_enabled=False,
        feature_doc_enabled=False,
        dev_spec_path=str(root / "Docs" / "AI" / "DevSpecs" / "bag.md"),
        feature_doc_path=str(root / "Docs" / "AI" / "Features" / "bag.md"),
        model="composer-2.5",
        phase="analyze",
        mode="work",
        flow_enabled=True,
        flow_path=str(flow_file_path(root, "bag")),
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _tasks() -> dict:
    return {
        "feature": "bag",
        "designDoc": "design.md",
        "prefabs": [],
        "tasks": [
            {
                "id": "T1",
                "title": "打开背包",
                "goal": "点按钮打开",
                "dependsOn": [],
                "files": ["Assets/Scripts/Bag.cs"],
                "prefabNodes": ["Canvas/Bag"],
                "acceptance": ["能打开"],
                "status": "pending",
            }
        ],
    }


def _write_flow(root: Path, slug: str = "bag", content: str | None = None) -> Path:
    path = flow_file_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content is not None else flow_template("bag", "design.md"), encoding="utf-8")
    return path


def _good_flow(root: Path, slug: str = "bag") -> Path:
    body = "\n".join(
        [
            "# bag 页面交互与数据流",
            "",
            "## 页面与入口",
            "",
            "- 主界面 → 背包面板",
            "",
            "## 页面交互流程",
            "",
            "```mermaid",
            "flowchart TD",
            "  A[主界面] --> B[背包面板]",
            "  B --> C[道具详情]",
            "```",
            "",
            "## 数据流向",
            "",
            "- 道具数据从 BagConfig 读，BagPanel 刷新列表，点击后 EventBus 发 BagItemSelected。",
            "",
            DRAFT_MARKER,
            "",
        ]
    )
    return _write_flow(root, slug, body)


def test_flow_template_is_recognisable() -> None:
    text = flow_template("bag", "design.md", "2026-08-16T10:00:00")
    assert "## 页面与入口" in text
    assert "```mermaid" in text
    assert DRAFT_MARKER in text
    assert "2026-08-16T10:00:00" in text
    assert is_confirmed(text) is False


def test_confirm_markdown_replaces_the_marker() -> None:
    draft = flow_template("bag", "design.md")
    confirmed = confirm_flow_markdown(draft, "2026-08-16T11:00:00")
    assert is_confirmed(confirmed) is True
    assert DRAFT_MARKER not in confirmed
    assert "confirmed by user at 2026-08-16T11:00:00" in confirmed


def test_flow_problems_reject_missing_and_empty_files(tmp_path: Path) -> None:
    path = flow_file_path(tmp_path, "bag")
    assert any("还没有写出来" in item for item in flow_problems(path))
    path.parent.mkdir(parents=True)
    path.write_text(DRAFT_MARKER, encoding="utf-8")
    problems = flow_problems(path)
    assert any("mermaid" in item for item in problems)
    assert any("空壳" in item or "内容太少" in item for item in problems)


def test_confirm_flow_file_and_gate(tmp_path: Path) -> None:
    path = _good_flow(tmp_path)
    assert flow_problems(path) == []
    assert flow_ready_for_gate(path) is False
    assert confirm_flow_file(path, "2026-08-16T12:00:00") is True
    assert flow_ready_for_gate(path) is True


def test_analyze_stops_at_the_flow_gate(tmp_path: Path) -> None:
    _project(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent()

    def on_send(prompt: str) -> None:
        if "「分析」阶段" in prompt:
            tasks_path = tmp_path / ".bulings" / "runs" / "bag" / "tasks.json"
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            tasks_path.write_text(json.dumps(_tasks(), ensure_ascii=False), encoding="utf-8")
            _good_flow(tmp_path)

    agent.on_send = on_send

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert code == 2
    assert state.phase == "flow"
    assert flow_ready_for_gate(flow_file_path(tmp_path, "bag")) is False
    # 停在门禁时不应该开始实现
    assert not any("「实现一个任务」阶段" in prompt for prompt in agent.prompts)


def test_resume_without_confirm_flow_stays_at_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _project(tmp_path)
    _good_flow(tmp_path)
    (tmp_path / ".bulings" / "runs" / "bag").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".bulings" / "runs" / "bag" / "tasks.json").write_text(
        json.dumps(_tasks(), ensure_ascii=False), encoding="utf-8"
    )
    state = _state(tmp_path, phase="flow")
    agent = FakeAgent()

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), True)

    assert code == 2
    assert state.phase == "flow"
    assert "--confirm-flow" in capsys.readouterr().err
    assert agent.prompts == []


def test_resume_confirm_flow_moves_to_implement(tmp_path: Path) -> None:
    _project(tmp_path)
    _good_flow(tmp_path)
    tasks_path = tmp_path / ".bulings" / "runs" / "bag" / "tasks.json"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(json.dumps(_tasks(), ensure_ascii=False), encoding="utf-8")
    state = _state(tmp_path, phase="flow", current_task_id="T1")
    agent = FakeAgent()

    def on_send(prompt: str) -> None:
        if "「实现一个任务」" in prompt:
            current = json.loads(tasks_path.read_text(encoding="utf-8"))
            for task in current["tasks"]:
                if task["id"] == "T1":
                    task["status"] = "done"
            tasks_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

    agent.on_send = on_send

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), True, confirm_flow=True)

    assert code == 0
    assert state.phase == "done"
    assert flow_ready_for_gate(flow_file_path(tmp_path, "bag")) is True
    assert any("「实现一个任务」" in prompt for prompt in agent.prompts)


def test_confirm_flow_without_a_file_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _project(tmp_path)
    state = _state(tmp_path, phase="flow")
    agent = FakeAgent()

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), True, confirm_flow=True)

    assert code == 2
    assert "流程图还不能确认" in capsys.readouterr().err
    assert state.phase == "flow"


def test_no_flow_skips_the_gate(tmp_path: Path) -> None:
    _project(tmp_path)
    state = _state(tmp_path)
    agent = FakeAgent()

    def on_send(prompt: str) -> None:
        if "「分析」阶段" in prompt:
            tasks_path = tmp_path / ".bulings" / "runs" / "bag" / "tasks.json"
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            tasks_path.write_text(json.dumps(_tasks(), ensure_ascii=False), encoding="utf-8")

    agent.on_send = on_send

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False, no_flow=True)

    assert code == 2  # 实现阶段没有 Agent 落盘，按原有逻辑停在 implement
    assert state.phase == "implement"
    assert not flow_file_path(tmp_path, "bag").exists()


def test_indie_mode_does_not_use_the_flow_gate(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".bulings" / "workflow.yaml").write_text("mode: indie\n", encoding="utf-8")
    state = _state(tmp_path, mode="indie", framework_enabled=False, flow_enabled=True)
    agent = FakeAgent()

    def on_send(prompt: str) -> None:
        if "「拆切片」阶段" in prompt:
            tasks_path = tmp_path / ".bulings" / "runs" / "bag" / "tasks.json"
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "feature": "bag",
                "designDoc": "design.md",
                "prefabs": [],
                "tasks": [
                    {
                        "id": "T1",
                        "title": "背包切片",
                        "slice": "背包",
                        "goal": "g",
                        "dependsOn": [],
                        "files": [],
                        "prefabNodes": [],
                        "framework": ["new: 背包数据"],
                        "acceptance": ["ok"],
                        "status": "pending",
                    }
                ],
            }
            tasks_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    agent.on_send = on_send

    code = _drive(agent, str(tmp_path), state, ProjectProfile(), False)

    assert state.phase == "implement"
    assert not flow_file_path(tmp_path, "bag").exists()


def _context(tmp_path: Path, **overrides) -> PromptContext:
    context = PromptContext(
        feature="bag",
        slug="bag",
        design_path="design.md",
        prefab_paths=["Assets/Bag.prefab"],
        tasks_path=".bulings/runs/bag/tasks.json",
        dev_spec_enabled=True,
        feature_doc_enabled=True,
        dev_spec_path="Docs/AI/DevSpecs/bag.md",
        feature_doc_path="Docs/AI/Features/bag.md",
        constraints="代码目录：Assets/Scripts",
        protected_paths=[],
        mode="work",
        flow_enabled=True,
        flow_path=".bulings/runs/bag/flow.md",
    )
    for key, value in overrides.items():
        setattr(context, key, value)
    return context


def _task() -> FeatureTask:
    return FeatureTask(
        id="T1",
        title="打开背包",
        goal="点按钮打开",
        depends_on=[],
        files=["Assets/Scripts/Bag.cs"],
        prefab_nodes=["Canvas/Bag"],
        acceptance=["能打开"],
        status="pending",
    )


def test_work_prompts_carry_the_binding_rule(tmp_path: Path) -> None:
    analyze = analyze_prompt(_context(tmp_path))
    implement = implement_prompt(_context(tmp_path), _task(), False)
    for prompt in (analyze, implement):
        assert "预制体内用脚本绑定" in prompt
        assert "transform.Find" in prompt


def test_work_analyze_prompt_requires_the_flow_doc(tmp_path: Path) -> None:
    prompt = analyze_prompt(_context(tmp_path))
    assert ".bulings/runs/bag/flow.md" in prompt
    assert "flow-status: draft" in prompt
    assert "mermaid" in prompt


def test_work_analyze_prompt_skips_the_flow_doc_when_disabled(tmp_path: Path) -> None:
    prompt = analyze_prompt(_context(tmp_path, flow_enabled=False))
    assert "flow.md" not in prompt


def test_work_implement_prompt_points_at_the_confirmed_flow(tmp_path: Path) -> None:
    prompt = implement_prompt(_context(tmp_path), _task(), False)
    assert "流程图（用户已确认）" in prompt