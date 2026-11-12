from __future__ import annotations

import json
from pathlib import Path

import pytest

from bulings.modes import ModeStrategy, requires_prefab, skill_dir_for, strategy_for
from bulings.modes.indie import (
    framework_prompt,
    indie_analyze_prompt,
    indie_document_prompt,
    indie_implement_prompt,
    validate_indie_tasks,
)
from bulings.prompts import PromptContext, analyze_prompt, document_prompt, implement_prompt
from bulings.tasks import FeatureTask, TaskFile


def _plan_payload(status: str = "done", hooks: list[str] | None = None) -> dict:
    return {
        "game": "game",
        "paradigm": "轻量自建",
        "root": "Assets/_Game",
        "systems": [{"id": "bootstrap", "title": "启动", "paths": ["Assets/_Game/Core"], "status": "done"}],
        "extensionPoints": [{"name": "EventBus", "howTo": "Send/Subscribe"}],
        "conventions": ["功能放 Features/"],
        "status": status,
    }


def _write_plan(root: Path, status: str = "done") -> str:
    path = root / ".bulings" / "indie" / "framework.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plan_payload(status), ensure_ascii=False), encoding="utf-8")
    return str(path)


def _context(root: Path, **overrides) -> PromptContext:
    context = PromptContext(
        feature="demo",
        slug="demo",
        design_path="design.md",
        prefab_paths=[],
        tasks_path=".bulings/runs/demo/tasks.json",
        dev_spec_enabled=True,
        feature_doc_enabled=True,
        dev_spec_path="Docs/AI/DevSpecs/demo.md",
        feature_doc_path="Docs/AI/Features/demo.md",
        constraints="代码目录：Assets/_Game",
        protected_paths=["Assets/ThirdParty"],
        mode="indie",
        game="game",
        framework_enabled=True,
        framework_plan_path=".bulings/indie/framework.json",
        framework_doc_path="Docs/AI/Frameworks/game.md",
        project_root=str(root),
    )
    for key, value in overrides.items():
        setattr(context, key, value)
    return context


def _task(**overrides) -> FeatureTask:
    payload = {
        "id": "T1",
        "title": "放置炮塔",
        "goal": "把炮塔放到格子上",
        "depends_on": [],
        "files": [],
        "prefab_nodes": [],
        "acceptance": ["能放下并看到"],
        "status": "pending",
        "slice": "放置炮塔",
        "framework": ["EventBus"],
    }
    payload.update(overrides)
    return FeatureTask(**payload)


def _task_file(*tasks: FeatureTask) -> TaskFile:
    return TaskFile(feature="demo", design_doc="design.md", prefabs=[], tasks=list(tasks))


def test_mode_tables() -> None:
    assert requires_prefab("work") is True
    assert requires_prefab("indie") is False
    assert skill_dir_for("work") == ".cursor/skills/work-feature"
    assert skill_dir_for("indie") == ".cursor/skills/indie-feature"
    with pytest.raises(ValueError):
        skill_dir_for("later")


def test_work_strategy_keeps_the_original_prompts(tmp_path: Path) -> None:
    context = _context(tmp_path)
    strategy = strategy_for("work", context)
    assert isinstance(strategy, ModeStrategy)
    assert strategy.requires_prefab is True
    assert strategy.prepare is None
    assert strategy.validate_tasks is None
    assert strategy.analyze_prompt(context) == analyze_prompt(context)
    task = _task()
    assert strategy.implement_prompt(context, task, False) == implement_prompt(context, task, False)
    assert strategy.document_prompt(context) == document_prompt(context)


def test_unknown_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        strategy_for("delivery", _context(tmp_path))


def test_indie_strategy_wires_hooks(tmp_path: Path) -> None:
    strategy = strategy_for("indie", _context(tmp_path))
    assert strategy.name == "indie"
    assert strategy.requires_prefab is False
    assert strategy.prepare is not None
    assert strategy.validate_tasks is not None


def test_framework_prompt_names_the_artifacts(tmp_path: Path) -> None:
    context = _context(tmp_path)
    prompt = framework_prompt(context, "", [])
    assert "建立框架" in prompt
    assert "frameworks.md" in prompt
    assert ".bulings/indie/framework.json" in prompt
    assert "Docs/AI/Frameworks/game.md" in prompt
    assert "Assets/ThirdParty" in prompt
    assert "status 只有全部系统可运行才写 done" in prompt


def test_framework_prompt_carries_the_draft_and_drift(tmp_path: Path) -> None:
    context = _context(tmp_path)
    prompt = framework_prompt(context, "核心系统：bootstrap（启动）", ["Assets/_Game/Core"])
    assert "不要重建已经落地的系统" in prompt
    assert "bootstrap" in prompt
    assert "磁盘上已经找不到" in prompt


def test_analyze_prompt_lists_hooks_and_new_rule(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    prompt = indie_analyze_prompt(_context(tmp_path))
    assert "拆切片" in prompt
    assert ".bulings/runs/demo/tasks.json" in prompt
    assert "bootstrap" in prompt and "EventBus" in prompt
    assert "new: <一句话说明>" in prompt
    assert "纵向切片" in prompt


def test_analyze_prompt_without_framework_still_asks_for_hooks(tmp_path: Path) -> None:
    prompt = indie_analyze_prompt(_context(tmp_path, framework_enabled=False))
    assert "框架基线：已关闭" in prompt
    assert "new: <说明>" in prompt


def test_implement_prompt_keeps_the_slice_on_the_framework(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    task = _task()
    prompt = indie_implement_prompt(_context(tmp_path), task, False)
    assert "只实现任务 T1" in prompt
    assert "挂载的框架点：EventBus" in prompt
    assert "extensionPoints" in prompt
    assert "不要为这一个切片另造一套" in prompt


def test_implement_prompt_marks_retry(tmp_path: Path) -> None:
    prompt = indie_implement_prompt(_context(tmp_path, framework_enabled=False), _task(blocked_reason="缺格子数据"), True)
    assert "只修补这一项" in prompt
    assert "缺格子数据" in prompt


def test_document_prompt_requires_extension_guidance(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    context = _context(tmp_path, knowledge_map="Docs/AI/Knowledge/MAP.md")
    prompt = indie_document_prompt(context)
    assert "feature-doc-template.md" in prompt
    assert "如何在这个框架上继续扩展" in prompt
    assert "extensionPoints" in prompt
    assert "knowledge-base" in prompt


def test_validate_accepts_known_hooks(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    assert validate_indie_tasks(_task_file(_task()), _context(tmp_path)) == []


def test_validate_rejects_missing_or_unknown_hooks(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    context = _context(tmp_path)
    missing = validate_indie_tasks(_task_file(_task(framework=[])), context)
    assert missing and "没有写 framework 挂载点" in missing[0]
    assert "EventBus" in missing[0]

    unknown = validate_indie_tasks(_task_file(_task(framework=["NoSuchSystem"])), context)
    assert unknown and "不在框架里" in unknown[0]


def test_validate_allows_new_hooks_with_a_note(tmp_path: Path) -> None:
    _write_plan(tmp_path)
    context = _context(tmp_path)
    assert validate_indie_tasks(_task_file(_task(framework=["new: 格子坐标服务"])), context) == []
    empty = validate_indie_tasks(_task_file(_task(framework=["new:"])), context)
    assert empty and "没有写说明" in empty[0]


def test_validate_reports_missing_framework_only(tmp_path: Path) -> None:
    errors = validate_indie_tasks(_task_file(_task(framework=["Whatever"])), _context(tmp_path))
    assert len(errors) == 1
    assert "框架基线缺失" in errors[0]


def test_validate_without_framework_only_needs_a_hook(tmp_path: Path) -> None:
    context = _context(tmp_path, framework_enabled=False)
    assert validate_indie_tasks(_task_file(_task(framework=["任意自定义"])), context) == []
    errors = validate_indie_tasks(_task_file(_task(framework=[])), context)
    assert errors and "没有写 framework 挂载点" in errors[0]
