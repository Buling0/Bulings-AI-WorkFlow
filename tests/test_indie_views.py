from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bulings import runner
from bulings.cli import dispatch
from bulings.runner import StatusCommand
from bulings.views import build_status, doctor_checks, doctor_lines, history_lines, status_json
from bulings.config import load_workflow_config
from bulings.gdd import DIMENSIONS, design_plan_path


def _setup(root: Path, mode: str = "indie") -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()
    (root / ".bulings").mkdir(parents=True, exist_ok=True)
    (root / ".bulings" / "workflow.yaml").write_text(f"mode: {mode}\n", encoding="utf-8")


def _plan(**overrides) -> dict:
    payload = {
        "slug": "td",
        "title": "塔防",
        "round": 2,
        "stage": "story",
        "status": "iterating",
        "dimensions": {name: {"summary": "s", "confirmed": name == "gameplay"} for name in DIMENSIONS},
        "options": [{"id": "S1", "dimension": "story", "label": "无剧情", "detail": "", "tradeoff": "缺记忆点"}],
        "chosen": [{"round": 2, "ids": ["S1"], "note": ""}],
    }
    payload.update(overrides)
    return payload


def _write_design(root: Path) -> None:
    path = design_plan_path(root, "td")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plan(), ensure_ascii=False), encoding="utf-8")


def _write_framework(root: Path, status: str = "done", systems_pending: int = 0) -> None:
    systems = [
        {"id": "bootstrap", "title": "启动", "paths": ["Assets/_Game/Core"], "status": "done"},
    ]
    for index in range(systems_pending):
        systems.append({"id": f"pending{index}", "title": "待做", "paths": [], "status": "pending"})
    payload = {
        "game": "td",
        "paradigm": "轻量自建",
        "root": "Assets/_Game",
        "systems": systems,
        "extensionPoints": [{"name": "EventBus", "howTo": "Send/Subscribe"}],
        "conventions": [],
        "status": status,
    }
    path = root / ".bulings" / "indie" / "framework.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_run(root: Path, phase: str = "implement") -> None:
    directory = root / ".bulings" / "runs" / "shop"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "state.json").write_text(json.dumps({"slug": "shop", "feature": "shop", "phase": phase}), encoding="utf-8")
    tasks = {
        "feature": "shop",
        "designDoc": "design.md",
        "prefabs": [],
        "tasks": [
            {"id": "T1", "title": "开门", "goal": "g", "dependsOn": [], "files": [], "prefabNodes": [],
             "acceptance": [], "status": "done"},
            {"id": "T2", "title": "买货", "goal": "g", "dependsOn": [], "files": [], "prefabNodes": [],
             "acceptance": [], "status": "blocked", "blockedReason": "后端：缺 10012 协议"},
        ],
    }
    (directory / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")


def test_status_lists_design_framework_and_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    _write_design(tmp_path)
    _write_framework(tmp_path, systems_pending=1)
    _write_run(tmp_path)

    code = runner.status_workflow(StatusCommand(project=str(tmp_path)))

    assert code == 0
    out = capsys.readouterr().out
    assert "模式：indie" in out
    assert "td：第 2 轮" in out
    assert "框架：就绪" in out
    assert "shop：implement（任务 1/2）" in out
    assert "后端：缺 10012 协议" in out
    assert "下一步：" in out


def test_status_json_is_parseable(tmp_path: Path) -> None:
    _setup(tmp_path)
    _write_design(tmp_path)
    _write_framework(tmp_path)
    _write_run(tmp_path, phase="analyze")

    view = build_status(str(tmp_path), load_workflow_config(tmp_path))
    payload = json.loads(status_json(view))

    assert payload["mode"] == "indie"
    assert payload["designs"][0]["slug"] == "td"
    assert payload["framework"]["ready"] is True
    assert payload["runs"][0]["blocked"][0]["id"] == "T2"
    assert payload["nextSteps"]


def test_status_cli_accepts_json_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    _write_design(tmp_path)

    code = dispatch(["status", "--project", str(tmp_path), "--json"])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["designs"][0]["slug"] == "td"


def test_status_without_artifacts_still_succeeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)

    code = runner.status_workflow(StatusCommand(project=str(tmp_path)))

    assert code == 0
    out = capsys.readouterr().out
    assert "策划案：还没有" in out
    assert "运行：还没有" in out


def test_doctor_reports_failures_for_a_non_unity_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = dispatch(["doctor", "--project", str(tmp_path)])

    assert code == 1
    assert "[FAIL] Unity 工程" in capsys.readouterr().out


def test_doctor_ok_on_a_prepared_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup(tmp_path)
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")

    items = doctor_checks(str(tmp_path), load_workflow_config(tmp_path))
    lines = doctor_lines(items)

    assert any("[OK] Unity 工程" in line for line in lines)
    assert any("[OK] CURSOR_API_KEY" in line for line in lines)
    assert any("[WARN] 框架基线" in line or "[OK] 框架基线" in line for line in lines)
    # MCP 探活可能因为环境不同而变，这里只要求有这一项
    assert any("Unity MCP" in line for line in lines)


def test_history_lines_mark_missing_snapshots() -> None:
    rounds = [
        {"round": 1, "recorded": True, "stage": "玩法核心循环", "status": "iterating", "options": ["G1"], "decision": ["G1"]},
        {"round": 2, "recorded": False, "stage": "-", "status": "-", "options": [], "decision": []},
    ]
    lines = history_lines("td", rounds)
    assert any("第 1 轮" in line for line in lines)
    assert any("快照缺失" in line for line in lines)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_audit_flags_protected_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    (tmp_path / ".bulings" / "workflow.yaml").write_text(
        "mode: indie\nproject:\n  protectedPaths:\n    - Assets/ThirdParty\n", encoding="utf-8"
    )
    (tmp_path / "Assets" / "ThirdParty").mkdir()
    _git(tmp_path, "init")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", "init")
    (tmp_path / "Assets" / "ThirdParty" / "x.cs").write_text("// x\n", encoding="utf-8")

    code = dispatch(["audit", "--project", str(tmp_path)])

    assert code == 1
    out = capsys.readouterr().out
    assert "Assets/ThirdParty/x.cs" in out
    assert "protectedPaths" in out


def test_audit_is_clean_on_a_fresh_workspace(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _setup(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-m", "init")

    code = dispatch(["audit", "--project", str(tmp_path)])

    assert code == 0
    assert "工作区没有改动" in capsys.readouterr().out
