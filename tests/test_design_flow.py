from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from bulings import runner
from bulings.cli import dispatch
from bulings.gdd import DIMENSIONS, design_plan_path
from bulings.install import install_workflow
from bulings.runner import DesignCommand

SLUG = "td"


class FakeRun:
    def __init__(self, run_id: str) -> None:
        self.id = run_id

    def supports(self, name: str) -> bool:
        return False

    def messages(self):  # pragma: no cover - supports 永远为假
        return iter(())

    def wait(self) -> SimpleNamespace:
        return SimpleNamespace(status="finished", id=self.id, result="")


class FakeAgent:
    def __init__(self, factory: "FakeFactory") -> None:
        self.agent_id = "agent-1"
        self._factory = factory

    def send(self, prompt: str) -> FakeRun:
        self._factory.prompts.append(prompt)
        if self._factory.on_send is not None:
            self._factory.on_send(prompt)
        return FakeRun(f"run-{len(self._factory.prompts)}")


class FakeFactory:
    """替代 cursor_sdk 的 Agent：create() 返回上下文管理器。"""

    def __init__(self, on_send=None) -> None:
        self.on_send = on_send
        self.prompts: list[str] = []
        self.agents: list[FakeAgent] = []

    def create(self, **kwargs: object) -> object:
        factory = self

        class _Context:
            def __enter__(self) -> FakeAgent:
                agent = FakeAgent(factory)
                factory.agents.append(agent)
                return agent

            def __exit__(self, *exc: object) -> bool:
                return False

        return _Context()


def _setup(root: Path, mode: str = "indie") -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()
    install_workflow(root)
    (root / ".bulings" / "workflow.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")


def _dimension(summary: str = "", confirmed: bool = False) -> dict:
    return {"summary": summary, "confirmed": confirmed}


def _option(option_id: str = "G1", **overrides) -> dict:
    payload = {
        "id": option_id,
        "dimension": "gameplay",
        "label": "实时塔防",
        "detail": "边打边建",
        "tradeoff": "上手更难",
    }
    payload.update(overrides)
    return payload


def _plan(**overrides) -> dict:
    payload = {
        "slug": SLUG,
        "title": "塔防 + 建造",
        "round": 1,
        "stage": "core",
        "status": "iterating",
        "dimensions": {name: _dimension() for name in DIMENSIONS},
        "options": [_option("G1"), _option("G2")],
        "chosen": [],
    }
    payload.update(overrides)
    return payload


def _write_plan(root: Path, **overrides) -> Path:
    path = design_plan_path(root, SLUG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plan(**overrides), ensure_ascii=False), encoding="utf-8")
    return path


def _doc_path(root: Path) -> Path:
    return root / "Docs" / "AI" / "GameDesigns" / f"{SLUG}.md"


def _write_doc(root: Path) -> Path:
    doc = _doc_path(root)
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# 塔防 + 建造 策划案\n", encoding="utf-8")
    return doc


def _round_writer(
    root: Path,
    *,
    options: list[dict] | None = None,
    chosen: list[str] | None = None,
    status: str = "iterating",
    stage: str = "story",
    write_doc: bool = True,
):
    """模拟 Agent 落盘：按提示词里的轮次写 design.json（和策划案正文）。"""

    def on_send(prompt: str) -> None:
        match = re.search(r"这是第 (\d+) 轮", prompt)
        round_no = int(match.group(1)) if match else 1
        payload = _plan(
            round=round_no,
            stage="done" if status == "done" else stage,
            status=status,
            options=[_option("G1"), _option("G2")] if options is None else options,
            chosen=[{"round": round_no, "ids": chosen or []}],
        )
        path = design_plan_path(root, SLUG)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        if write_doc:
            _write_doc(root)

    return on_send


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")


def _use_agent(monkeypatch: pytest.MonkeyPatch, factory: FakeFactory) -> None:
    monkeypatch.setattr(runner, "Agent", factory)


def test_first_round_reads_the_idea_and_records_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path)
    idea = tmp_path / "idea.md"
    idea.write_text("想做一个白天建造、夜里守塔的小游戏", encoding="utf-8")
    factory = FakeFactory(_round_writer(tmp_path))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), idea=str(idea), name=SLUG))

    assert code == 0
    assert len(factory.agents) == 1
    assert "这是第 1 轮" in factory.prompts[0]
    assert "玩法灵感" in factory.prompts[0]
    assert "本轮要求" in factory.prompts[0]

    brief = tmp_path / ".bulings" / "design" / SLUG / "brief.md"
    assert brief.is_file()
    assert "白天建造、夜里守塔" in brief.read_text(encoding="utf-8")
    assert design_plan_path(tmp_path, SLUG).is_file()


def test_first_round_prints_the_options_and_next_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path))
    _use_agent(monkeypatch, factory)

    assert runner.design_workflow(DesignCommand(project=str(tmp_path), idea="塔防", name=SLUG)) == 0

    out = capsys.readouterr().out
    assert "本轮选项" in out
    assert "G1" in out
    assert "--decide" in out


def test_inline_idea_needs_a_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), idea="一段没有名字的灵感"))

    assert code == 1
    assert "缺少策划案名" in capsys.readouterr().err


def test_idea_is_refused_once_a_plan_exists(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), idea="重来一次", name=SLUG))

    assert code == 1
    assert "--finish" in capsys.readouterr().err


def test_work_mode_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path, mode="work")
    factory = FakeFactory()
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), idea="塔防", name=SLUG))

    assert code == 1
    assert "独游模式" in capsys.readouterr().err
    assert factory.agents == []


def test_unknown_option_is_rejected_before_running_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="Z9"))

    assert code == 1
    err = capsys.readouterr().err
    assert "Z9" in err
    assert "G1" in err
    assert factory.agents == []


def test_decide_advances_the_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path, options=[_option("S1", dimension="story"), _option("S2", dimension="story")], chosen=["G1"]))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="G1"))

    assert code == 0
    assert "这是第 2 轮" in factory.prompts[0]
    assert "G1" in factory.prompts[0]
    out = capsys.readouterr().out
    assert "S1" in out


def test_note_alone_advances_the_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, note="想要更休闲一点"))

    assert code == 0
    assert "想要更休闲一点" in factory.prompts[0]


def test_round_that_does_not_advance_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path, round=1)
    factory = FakeFactory(_round_writer(tmp_path, chosen=["G1"]))
    # 让 Agent 忘了推进轮次：把 round 写回 1
    def stuck(prompt: str) -> None:
        payload = _plan(round=1, chosen=[{"round": 1, "ids": ["G1"]}])
        path = design_plan_path(tmp_path, SLUG)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _write_doc(tmp_path)

    factory.on_send = stuck
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="G1"))

    assert code == 2
    assert "应该写 round 2" in capsys.readouterr().err


def test_single_option_round_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path, options=[_option("G1")], chosen=["G1"]))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="G1"))

    assert code == 2
    assert "至少要给 2 个选项" in capsys.readouterr().err


def test_decision_must_be_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path, chosen=[]))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="G1"))

    assert code == 2
    assert "没有写进 chosen" in capsys.readouterr().err


def test_invalid_design_json_stops_the_round(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)

    def broken(prompt: str) -> None:
        path = design_plan_path(tmp_path, SLUG)
        path.write_text("{not json", encoding="utf-8")

    factory = FakeFactory(broken)
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, decide="G1"))

    assert code == 2
    assert "不合法或没写出来" in capsys.readouterr().err


def test_finish_requires_done_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path, status="iterating"))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, finish=True))

    assert code == 2
    assert "status 必须写成 done" in capsys.readouterr().err


def test_finish_writes_the_final_doc_and_points_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory(_round_writer(tmp_path, options=[], status="done"))
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, finish=True))

    assert code == 0
    assert "定稿" in factory.prompts[0]
    out = capsys.readouterr().out
    assert "策划案已定稿" in out
    assert "bulings run" in out
    assert _doc_path(tmp_path).is_file()


def test_finish_without_a_plan_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG, finish=True))

    assert code == 1
    assert "--idea" in capsys.readouterr().err


def test_status_only_does_not_start_an_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory()
    _use_agent(monkeypatch, factory)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG))

    assert code == 0
    out = capsys.readouterr().out
    assert "进度：第 1 轮" in out
    assert "G2" in out
    assert factory.agents == []


def test_status_of_unknown_plan_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)

    code = runner.design_workflow(DesignCommand(project=str(tmp_path), name=SLUG))

    assert code == 1
    assert "--idea" in capsys.readouterr().err


def test_cli_wires_the_design_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _setup(tmp_path)
    _write_plan(tmp_path)
    factory = FakeFactory()
    _use_agent(monkeypatch, factory)

    code = dispatch(["design", "--project", str(tmp_path), "--name", SLUG])

    assert code == 0
    assert "本轮选项" in capsys.readouterr().out
    assert factory.agents == []


def test_cli_reports_a_missing_design_argument(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)

    code = dispatch(["design", "--project", str(tmp_path)])

    assert code == 1
    assert "--idea" in capsys.readouterr().err
