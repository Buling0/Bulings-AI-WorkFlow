from __future__ import annotations

import hashlib
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from bulings.audit import audit_workspace, format_audit_errors
from bulings.config import (
    ProjectProfile,
    RunOverrides,
    feature_from_design,
    feature_token,
    knowledge_map_path,
    load_workflow_config,
    resolve_doc_path,
    resolve_run_config,
    to_project_path,
)
from bulings.framework import hook_aliases, plan_summary, read_framework_plan
from bulings.flowchart import (
    confirm_flow_file,
    describe_flow_gate,
    flow_file_path,
    flow_problems,
)
from bulings.gdd import (
    GddOption,
    design_brief_path,
    design_plan_path,
    design_round_snapshot_path,
    dimension_title,
    find_options,
    finish_dimension_errors,
    gdd_summary,
    is_finished,
    option_ids,
    parse_decisions,
    pending_dimensions,
    plan_status_lines,
    read_gdd_plan,
    stage_title,
    validate_round,
    write_design_snapshot,
)
from bulings.views import (
    build_status,
    design_history,
    doctor_checks,
    doctor_lines,
    history_lines,
    status_json,
    status_lines,
)
from bulings.install import is_unity_project, mcp_server_entry
from bulings.modes import (
    INDIE_DESIGN_SKILL_DIR,
    ModeEnv,
    ModeStrategy,
    requires_prefab,
    skill_dir_for,
    strategy_for,
)
from bulings.prompts import (
    PromptContext,
    GddContext,
    KnowledgeContext,
    SplitContext,
    format_project_constraints,
    gdd_finalize_prompt,
    gdd_round_prompt,
    knowledge_prompt,
    split_prompt,
)
from bulings.tasks import (
    mark_task_in_progress,
    read_task_file,
    reopen_blocked_task,
    select_next_task,
    unmet_dependencies,
    write_task_file,
)

BLOCKED_GAP_NOTE = (
    "分析发现阻断性缺失，已停在分析阶段，未进入写代码。"
    "按 tasks.json 里 blockedReason 的类别（策划 / 后端 / 美术 / 前端）补齐后 resume。"
)


@dataclass
class RunCommand:
    project: str
    design: str
    prefabs: list[str]
    name: str | None
    overrides: RunOverrides


@dataclass
class SplitCommand:
    project: str
    design: str
    name: str | None = None
    output: str | None = None
    model: str | None = None


@dataclass
class KnowledgeCommand:
    project: str
    action: str
    name: str | None = None
    model: str | None = None


@dataclass
class DesignCommand:
    """策划案迭代：--idea 起第一轮，--decide/--note 推进，--finish 定稿。"""

    project: str
    idea: str | None = None
    name: str | None = None
    decide: str | None = None
    note: str | None = None
    finish: bool = False
    force: bool = False
    history: bool = False
    json: bool = False
    model: str | None = None


@dataclass
class ResumeCommand:
    project: str
    slug: str
    confirm_flow: bool = False
    no_flow: bool = False


@dataclass
class AuditCommand:
    project: str
    json: bool = False


@dataclass
class StatusCommand:
    project: str
    as_json: bool = False


@dataclass
class DoctorCommand:
    project: str


@dataclass
class RunState:
    slug: str
    feature: str
    design_path: str
    prefabs: list[str]
    dev_spec_enabled: bool
    feature_doc_enabled: bool
    dev_spec_path: str
    feature_doc_path: str
    model: str
    phase: str
    agent_id: str | None = None
    current_task_id: str | None = None
    last_run_id: str | None = None
    mode: str = "work"
    game: str = ""
    framework_enabled: bool = False
    framework_plan_path: str = ""
    framework_doc_path: str = ""
    framework_doc_enabled: bool = True
    flow_enabled: bool = True
    flow_path: str = ""


def run_workflow(command: RunCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    config = load_workflow_config(project_root)
    if requires_prefab(config.mode) and not command.prefabs:
        print("工作模式至少提供一个 --prefab <预制体>（独游模式可以不给）。", file=sys.stderr)
        return 1

    design_path = _resolve_existing_file(command.design, project_root)
    prefabs = [_resolve_existing_file(item, project_root) for item in command.prefabs]
    for prefab in prefabs:
        _warn_if_not_prefab(prefab)

    feature_source = command.name if command.name and command.name.strip() else feature_from_design(design_path)
    resolved = resolve_run_config(config, project_root, feature_source, command.overrides)
    state = RunState(
        slug=resolved.feature,
        feature=resolved.feature,
        design_path=design_path,
        prefabs=prefabs,
        dev_spec_enabled=resolved.dev_spec_enabled,
        feature_doc_enabled=resolved.feature_doc_enabled,
        dev_spec_path=resolved.dev_spec_path,
        feature_doc_path=resolved.feature_doc_path,
        model=resolved.model,
        phase="analyze",
        mode=config.mode,
        game=resolved.game,
        framework_enabled=resolved.framework_enabled,
        framework_plan_path=resolved.framework_plan_path,
        framework_doc_path=resolved.framework_doc_path,
        framework_doc_enabled=resolved.framework_doc_enabled,
        flow_enabled=resolved.flow_enabled,
        flow_path=resolved.flow_path,
    )

    existing = _read_state(_state_path(project_root, state.slug))
    if existing is not None and existing.phase != "done":
        print(
            f"已有未完成的运行 {state.slug}。继续请执行：\n{_resume_hint(project_root, state.slug)}",
            file=sys.stderr,
        )
        return 1

    if _ensure_skill(project_root, skill_dir_for(state.mode)) != 0:
        return 1

    api_key = _require_api_key()
    if not api_key:
        return 1

    try:
        with Agent.create(
            model=state.model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=project_root, setting_sources=["project"]),
        ) as agent:
            state.agent_id = agent.agent_id
            print(f"agentId={agent.agent_id}", flush=True)
            _save_state(project_root, state)
            return _drive(agent, project_root, state, config.project, False, no_flow=command.overrides.no_flow)
    except CursorAgentError as error:
        return _handle_startup_error(error)


def split_workflow(command: SplitCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    config = load_workflow_config(project_root)
    if config.mode == "indie":
        print(
            "前端分离只在工作模式使用。独游工程需要分离时，把 workflow.yaml 的 mode 临时改成 work "
            "跑一次 split，再改回 indie。",
            file=sys.stderr,
        )
        return 1

    design_path = _resolve_existing_file(command.design, project_root)
    feature = feature_token(command.name if command.name and command.name.strip() else feature_from_design(design_path))
    pattern = command.output if command.output else config.client_spec_path
    output_path = resolve_doc_path(pattern, feature, project_root)

    skill = Path(project_root) / ".cursor" / "skills" / "client-split" / "SKILL.md"
    if not skill.exists():
        print("工程里还没有前端分离 Skill。请先执行 bulings init --project <Unity工程>", file=sys.stderr)
        return 1

    api_key = _require_api_key()
    if not api_key:
        return 1

    context = SplitContext(
        feature=feature,
        design_path=to_project_path(project_root, design_path),
        output_path=to_project_path(project_root, output_path),
        constraints=format_project_constraints(config.project, knowledge_map_path(config, project_root) or ""),
        protected_paths=list(config.project.protected_paths),
    )
    state = RunState(
        slug=feature,
        feature=feature,
        design_path=design_path,
        prefabs=[],
        dev_spec_enabled=False,
        feature_doc_enabled=False,
        dev_spec_path="",
        feature_doc_path="",
        model=(command.model or "").strip() or config.model,
        phase="split",
        mode=config.mode,
        flow_enabled=False,
    )
    try:
        with Agent.create(
            model=state.model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=project_root, setting_sources=["project"]),
        ) as agent:
            print(f"agentId={agent.agent_id}", flush=True)
            print("[前端分离] 开始", file=sys.stderr)
            code = _send_plain(agent, split_prompt(context))
    except CursorAgentError as error:
        return _handle_startup_error(error)
    if code != 0:
        return code
    if not os.path.isfile(output_path):
        print(f"Agent 结束但没有写出 {context.output_path}。", file=sys.stderr)
        return 2
    print(f"客户端需求文档已写入 {context.output_path}")
    print(f"接着做开发：bulings run --project <工程> --design {context.output_path} --prefab <预制体>")
    return 0


def knowledge_workflow(command: KnowledgeCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error
    if command.action not in ("init", "update", "check"):
        print(f"未知的知识库动作: {command.action}（可选 init、update、check）", file=sys.stderr)
        return 1

    config = load_workflow_config(project_root)
    if not config.knowledge.enabled:
        print("workflow.yaml 里 knowledge.enabled 为 false，知识库未启用。", file=sys.stderr)
        return 1

    skill = Path(project_root) / ".cursor" / "skills" / "knowledge-base" / "SKILL.md"
    if not skill.exists():
        print("工程里还没有知识库 Skill。请先执行 bulings init --project <Unity工程>", file=sys.stderr)
        return 1
    if command.action != "init" and knowledge_map_path(config, project_root) is None:
        print("知识库还没建立（找不到 MAP.md）。请先执行 bulings kb --action init", file=sys.stderr)
        return 1
    if command.action == "update" and not (command.name and command.name.strip()):
        print("update 需要 --name <功能名>（对应 .bulings/runs/<功能名>/tasks.json）", file=sys.stderr)
        return 1

    api_key = _require_api_key()
    if not api_key:
        return 1

    feature = feature_token(command.name) if command.name and command.name.strip() else ""
    context = KnowledgeContext(
        action=command.action,
        root=config.knowledge.root,
        feature=feature,
        tasks_path=to_project_path(project_root, str(_tasks_file(project_root, feature))) if feature else "",
        constraints=format_project_constraints(config.project),
        protected_paths=list(config.project.protected_paths),
    )
    model = (command.model or "").strip() or config.model
    try:
        with Agent.create(
            model=model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=project_root, setting_sources=["project"]),
        ) as agent:
            print(f"agentId={agent.agent_id}", flush=True)
            print(f"[知识库 {command.action}] 开始", file=sys.stderr)
            code = _send_plain(agent, knowledge_prompt(context))
    except CursorAgentError as error:
        return _handle_startup_error(error)
    if code != 0:
        return code
    if command.action == "init" and knowledge_map_path(config, project_root) is None:
        print("Agent 结束但没有写出 MAP.md。", file=sys.stderr)
        return 2
    print(f"知识库 {command.action} 完成，根目录 {config.knowledge.root}")
    return 0


def design_workflow(command: DesignCommand) -> int:
    """从玩法灵感迭代策划案。一轮一次 Agent，状态全在 design.json 里。"""
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    config = load_workflow_config(project_root)
    if config.mode != "indie":
        print("策划案迭代只在独游模式使用。把 workflow.yaml 的 mode 改成 indie 再试。", file=sys.stderr)
        return 1

    idea_text, idea_source = _read_idea(command.idea, project_root)
    name = (command.name or "").strip()
    if not name and idea_source:
        name = Path(idea_source).stem
    if not name:
        print("缺少策划案名：用一段文字当灵感时请给 --name <名字>。", file=sys.stderr)
        return 1
    slug = feature_token(name)

    plan_path = design_plan_path(project_root, slug)
    brief_path = design_brief_path(project_root, slug)
    doc_path = resolve_doc_path(config.design.path, slug, project_root)
    previous = read_gdd_plan(plan_path)
    wanted = parse_decisions(command.decide) if command.decide else []
    note = (command.note or "").strip()

    if command.history:
        return _print_design_history(project_root, slug, command.json)

    if command.idea and previous is not None:
        print(
            f"{slug} 已经有第 {previous.round} 轮的策划案。继续用 --decide / --note，定稿用 --finish；"
            "要重来请换一个 --name。",
            file=sys.stderr,
        )
        return 1
    if previous is None and not command.idea:
        print(f"还没有 {slug} 的策划案。先用 --idea 起第一轮。", file=sys.stderr)
        return 1

    found: list[GddOption] = []
    if wanted:
        assert previous is not None
        found, missing = find_options(previous, wanted)
        if missing:
            print("这些选项不在当前这一轮里：" + "、".join(missing), file=sys.stderr)
            available = "、".join(sorted(option_ids(previous))) or "（这一轮没有选项）"
            print(f"可选的 id：{available}", file=sys.stderr)
            return 1

    if not command.idea and not wanted and not note and not command.finish:
        assert previous is not None
        _print_design_status(project_root, previous, slug, config.design.rounds)
        return 0

    if _ensure_skill(project_root, INDIE_DESIGN_SKILL_DIR) != 0:
        return 1
    api_key = _require_api_key()
    if not api_key:
        return 1

    if idea_text is not None:
        _write_design_brief(brief_path, idea_text, idea_source, project_root)

    doc_before = _design_doc_signature(doc_path)
    round_no = previous.round + 1 if previous is not None else 1
    stage = _next_design_stage(previous)
    context = GddContext(
        slug=slug,
        title=(previous.title if previous is not None else slug),
        brief_path=to_project_path(project_root, str(brief_path)),
        plan_path=to_project_path(project_root, str(plan_path)),
        doc_path=to_project_path(project_root, doc_path),
        round_no=round_no,
        stage=stage,
        stage_title=stage_title(stage),
        options_count=config.design.options,
        target_rounds=config.design.rounds,
        summary=gdd_summary(previous),
        decisions=[_decision_line(option) for option in found],
        note=note,
        first_round=previous is None,
        constraints=format_project_constraints(config.project, "", "indie-design"),
        protected_paths=list(config.project.protected_paths),
    )
    prompt = gdd_finalize_prompt(context) if command.finish else gdd_round_prompt(context)
    model = (command.model or "").strip() or config.model

    try:
        with Agent.create(
            model=model,
            api_key=api_key,
            local=LocalAgentOptions(cwd=project_root, setting_sources=["project"]),
        ) as agent:
            print(f"agentId={agent.agent_id}", flush=True)
            print(f"[策划案] 第 {round_no} 轮开始（{context.stage_title}）", file=sys.stderr)
            code = _send_plain(agent, prompt)
    except CursorAgentError as error:
        return _handle_startup_error(error)
    if code != 0:
        return code

    current = read_gdd_plan(plan_path)
    if current is None:
        print(
            f"第 {round_no} 轮结束，但 {context.plan_path} 不合法或没写出来，已停止。",
            file=sys.stderr,
        )
        return 2
    errors = validate_round(previous, current, wanted, note_given=bool(note))
    if errors:
        print(f"第 {round_no} 轮没有推进到位，已停止：", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 2

    _save_design_snapshot(project_root, slug, round_no, plan_path)
    if _design_doc_signature(doc_path) == doc_before:
        print(
            f"警告：第 {round_no} 轮 {context.doc_path} 没有变化。这一轮的状态文件更新了，正文没更新。",
            file=sys.stderr,
        )

    if command.finish:
        if current.status != "done":
            print("定稿那一轮 status 必须写成 done。", file=sys.stderr)
            return 2
        dimension_errors = finish_dimension_errors(current)
        if dimension_errors:
            if not command.force:
                print("定稿没有通过：", file=sys.stderr)
                for item in dimension_errors:
                    print(f"- {item}", file=sys.stderr)
                return 2
            print("警告：--force 绕过了维度确认要求。", file=sys.stderr)
        if not os.path.isfile(doc_path) or os.path.getsize(doc_path) == 0:
            print(f"定稿结束，但 {context.doc_path} 不存在或是空的。", file=sys.stderr)
            return 2
        print(f"策划案已定稿：{context.doc_path}")
        print(f"接着做：bulings run --project <Unity工程> --design {context.doc_path} --name {slug}")
        return 0

    _print_design_status(project_root, current, slug, config.design.rounds)
    return 0


def _design_doc_signature(path: str) -> str | None:
    """策划案正文的指纹。用内容哈希，mtime 靠不住（同尺寸快速重写可能不变）。"""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    return hashlib.sha256(data).hexdigest()


def _save_design_snapshot(project_root: str, slug: str, round_no: int, plan_path: Path) -> None:
    try:
        content = plan_path.read_text(encoding="utf-8")
    except OSError:
        return
    write_design_snapshot(project_root, slug, round_no, content)


def status_workflow(command: StatusCommand) -> int:
    project_root = os.path.abspath(command.project)
    config = _load_config_or_explain(project_root)
    if config is None:
        return 1
    view = build_status(project_root, config)
    if command.as_json:
        print(status_json(view))
        return 0
    for line in status_lines(view):
        print(line)
    return 0


def doctor_workflow(command: DoctorCommand) -> int:
    project_root = os.path.abspath(command.project)
    config = _load_config_or_explain(project_root)
    items = doctor_checks(project_root, config)
    for line in doctor_lines(items):
        print(line)
    return 1 if any(item.level == "fail" for item in items) else 0


def _load_config_or_explain(project_root: str) -> Any:
    try:
        return load_workflow_config(project_root)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return None


def _print_design_history(project_root: str, slug: str, as_json: bool) -> int:
    rounds = design_history(project_root, slug)
    if as_json:
        print(json.dumps({"slug": slug, "rounds": rounds}, ensure_ascii=False, indent=2))
        return 0
    for line in history_lines(slug, rounds):
        print(line)
    return 0


def _read_idea(raw: str | None, project_root: str) -> tuple[str | None, str | None]:
    """--idea 既可以是文件路径，也可以是一段文字。返回 (文本, 来源文件)。"""
    if not raw:
        return None, None
    for candidate in (raw, os.path.join(project_root, raw)):
        if os.path.isfile(candidate):
            return Path(candidate).read_text(encoding="utf-8"), os.path.abspath(candidate)
    return raw, None


def _write_design_brief(
    brief_path: Path,
    text: str,
    source: str | None,
    project_root: str,
) -> None:
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    source_line = f"来源：{to_project_path(project_root, source)}" if source else "来源：命令行 --idea"
    content = "\n".join(["# 玩法灵感", "", source_line, "", text.rstrip(), ""])
    brief_path.write_text(content, encoding="utf-8", newline="\n")


def _next_design_stage(previous: Any) -> str:
    """这一轮该推进哪个阶段：按 玩法 → 剧情 → 风格 → 流程 → 收尾 走。"""
    if previous is None:
        return "core"
    if is_finished(previous):
        return "done"
    mapping = {"gameplay": "core", "story": "story", "style": "style", "flow": "flow"}
    pending = pending_dimensions(previous)
    return mapping[pending[0]] if pending else "polish"


def _decision_line(option: GddOption) -> str:
    parts = [f"- {option.id}（{dimension_title(option.dimension)}）{option.label}"]
    if option.detail:
        parts.append(f"：{option.detail}")
    if option.tradeoff:
        parts.append(f"；代价：{option.tradeoff}")
    return "".join(parts)


def _print_design_status(project_root: str, plan: Any, slug: str, suggested_rounds: int = 0) -> None:
    for line in plan_status_lines(plan, suggested_rounds):
        print(line)
    if plan.options:
        print("下一步：bulings design --project <Unity工程> --name " + slug + " --decide <id>[,<id>]")
        print('       补充想法：--note "..."；定稿：--finish；回看：--history；只看状态：不带参数再跑一次')
    else:
        print('这一轮没有新选项。用 --note 补充，或 --finish 定稿。')
        print(f"回看每轮记录：bulings design --project <Unity工程> --name {slug} --history")


def resume_workflow(command: ResumeCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    slug = feature_token(command.slug)
    state = _read_state(_state_path(project_root, slug))
    if state is None:
        print(f"找不到运行 {slug} 的 state.json。", file=sys.stderr)
        return 1
    if not state.agent_id:
        print(f"运行 {slug} 没有 agentId，无法恢复。", file=sys.stderr)
        return 1
    if state.phase == "done":
        print(f"运行 {slug} 已完成。")
        return 0

    config = load_workflow_config(project_root)
    if state.mode != config.mode:
        print(
            f"运行 {slug} 是按 {state.mode} 模式建立的，当前 workflow.yaml 是 {config.mode}。"
            f"把 mode 改回 {state.mode} 再继续，或另开一次运行。",
            file=sys.stderr,
        )
        return 1

    if _ensure_skill(project_root, skill_dir_for(state.mode)) != 0:
        return 1

    api_key = _require_api_key()
    if not api_key:
        return 1

    try:
        with Agent.resume(
            state.agent_id,
            AgentOptions(
                api_key=api_key,
                model=state.model,
                local=LocalAgentOptions(cwd=project_root, setting_sources=["project"]),
            ),
        ) as agent:
            print(f"agentId={agent.agent_id}", flush=True)
            return _drive(
                agent,
                project_root,
                state,
                config.project,
                True,
                command.confirm_flow,
                command.no_flow,
            )
    except CursorAgentError as error:
        return _handle_startup_error(error)


def _drive(
    agent: Any,
    project_root: str,
    state: RunState,
    project: ProjectProfile,
    resuming: bool,
    confirm_flow: bool = False,
    no_flow: bool = False,
) -> int:
    strategy = strategy_for(state.mode, _prompt_context(project_root, state, project))
    prepared = _run_prepare(agent, project_root, state, strategy)
    if prepared != 0:
        return prepared
    _audit_after_phase(project_root, project, "框架")

    if no_flow:
        state.flow_enabled = False
    if state.phase == "flow" and confirm_flow:
        problems = _confirm_flow(project_root, state)
        if problems:
            print("流程图还不能确认：", file=sys.stderr)
            for item in problems:
                print(f"- {item}", file=sys.stderr)
            print(_resume_hint(project_root, state.slug), file=sys.stderr)
            return 2
        state.phase = "implement"
        _save_state(project_root, state)
    if state.phase == "flow" and no_flow:
        print("[流程图] 已用 --no-flow 跳过确认，直接进入实现。", file=sys.stderr)
        state.phase = "implement"
        _save_state(project_root, state)

    if state.phase == "analyze":
        analyzed = _run_analyze(agent, project_root, state, project, strategy)
        if analyzed != 0:
            return analyzed
        _audit_after_phase(project_root, project, "分析")
        resuming = False
        if _flow_gate_applies(state) and not (confirm_flow or no_flow):
            return _stop_at_flow_gate(project_root, state)

    if state.phase == "flow":
        # 走到这里说明用户没有确认流程图（确认走 resume --confirm-flow）。
        return _stop_at_flow_gate(project_root, state)

    if state.phase == "document" and not _all_tasks_done(project_root, state.slug):
        state.phase = "implement"

    if state.phase == "implement":
        if resuming:
            _reopen_if_needed(project_root, state)
        implemented = _run_implement(agent, project_root, state, project, strategy)
        if implemented != 0:
            return implemented

    if not state.feature_doc_enabled:
        state.phase = "done"
        state.current_task_id = None
        _save_state(project_root, state)
        print("功能已完成，未生成功能说明。")
        return 0

    state.phase = "document"
    state.current_task_id = None
    _save_state(project_root, state)
    documented = _run_document(agent, project_root, state, project, strategy)
    if documented != 0:
        return documented
    _audit_after_phase(project_root, project, "功能说明")

    state.phase = "done"
    _save_state(project_root, state)
    print(f"功能说明已写入 {to_project_path(project_root, state.feature_doc_path)}")
    return 0


def _audit_after_phase(project_root: str, project: ProjectProfile, phase: str) -> None:
    """每个阶段结束后只报错误级审计问题，不改变退出码。"""
    report = audit_workspace(project_root, project.protected_paths, project.code_roots)
    for line in format_audit_errors(report):
        print(f"{line}（{phase}阶段结束）", file=sys.stderr)


def _flow_gate_applies(state: RunState) -> bool:
    """流程图门禁只管工作模式；独游模式有自己的框架和切片校验。"""
    return state.mode == "work" and state.flow_enabled


def _flow_file(project_root: str, state: RunState) -> Path:
    if state.flow_path:
        return Path(state.flow_path)
    return flow_file_path(project_root, state.slug)


def _stop_at_flow_gate(project_root: str, state: RunState) -> int:
    state.phase = "flow"
    _save_state(project_root, state)
    print(describe_flow_gate(state.feature, state.slug, _flow_file(project_root, state)), file=sys.stderr)
    print(
        "流程图确认之前不进入写代码。看不到图就先补 `.bulings/runs/<功能名>/flow.md`。",
        file=sys.stderr,
    )
    return 2


def _confirm_flow(project_root: str, state: RunState) -> list[str]:
    """写完确认标记。返回空列表表示确认成功。"""
    path = _flow_file(project_root, state)
    problems = flow_problems(path)
    if problems:
        return problems
    if not confirm_flow_file(path, datetime.now().isoformat(timespec="seconds")):
        return [f"写不了流程图的确认标记：{path}"]
    print(f"[流程图] 已确认：{path}", file=sys.stderr)
    return []


def audit_workflow(command: AuditCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    config = load_workflow_config(project_root)
    report = audit_workspace(project_root, config.project.protected_paths, config.project.code_roots)
    if command.json:
        payload = {
            "git": report.is_git,
            "changed": report.changed,
            "findings": [
                {"level": item.level, "path": item.path, "message": item.message} for item in report.findings
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for line in report.lines():
            print(line)
        if report.errors:
            print("审计发现错误级问题：先处理这些文件，再提交。", file=sys.stderr)
    if not report.ok:
        return 1
    return 0


def _run_prepare(agent: Any, project_root: str, state: RunState, strategy: ModeStrategy) -> int:
    """模式自己的前置阶段。独游模式靠它在写功能前建立框架。"""
    if strategy.prepare is None:
        return 0

    def send(prompt: str) -> int:
        return _send(agent, project_root, state, prompt)

    def save_state() -> None:
        _save_state(project_root, state)

    env = ModeEnv(
        project_root=project_root,
        context=_prompt_context(project_root, state, load_workflow_config(project_root).project),
        save_state=save_state,
        send=send,
    )
    resumed_phase = "analyze" if state.phase in ("framework", "analyze") else state.phase
    state.phase = "framework"
    _save_state(project_root, state)
    code = strategy.prepare(env)
    if code != 0:
        return code
    state.phase = resumed_phase
    _save_state(project_root, state)
    return 0


def _run_analyze(
    agent: Any,
    project_root: str,
    state: RunState,
    project: ProjectProfile,
    strategy: ModeStrategy,
) -> int:
    _run_directory(project_root, state.slug).mkdir(parents=True, exist_ok=True)
    print("[分析] 开始", file=sys.stderr)
    context = _prompt_context(project_root, state, project)
    code = _send(agent, project_root, state, strategy.analyze_prompt(context))
    if code != 0:
        return code

    tasks = read_task_file(_tasks_file(project_root, state.slug))
    if tasks is None:
        state.phase = "analyze"
        _save_state(project_root, state)
        print("分析结束但没有合法的 tasks.json，已停止，未进入写代码。", file=sys.stderr)
        return 2

    if strategy.validate_tasks is not None:
        errors = strategy.validate_tasks(tasks, context)
        if errors:
            state.phase = "analyze"
            _save_state(project_root, state)
            print("分析结束但切片没有挂在框架上，已停止，未进入写代码：", file=sys.stderr)
            for item in errors:
                print(f"- {item}", file=sys.stderr)
            print(_resume_hint(project_root, state.slug), file=sys.stderr)
            return 2

    blocked = [task for task in tasks.tasks if task.status == "blocked"]
    if blocked:
        state.phase = "analyze"
        _save_state(project_root, state)
        print(BLOCKED_GAP_NOTE, file=sys.stderr)
        for task in blocked:
            print(f"- {task.id} {task.title}：{task.blocked_reason or '未写明原因'}", file=sys.stderr)
        print(_resume_hint(project_root, state.slug), file=sys.stderr)
        return 2

    state.phase = "implement"
    _save_state(project_root, state)
    return 0


def _run_implement(
    agent: Any,
    project_root: str,
    state: RunState,
    project: ProjectProfile,
    strategy: ModeStrategy,
) -> int:
    tasks_path = _tasks_file(project_root, state.slug)
    while True:
        task_file = read_task_file(tasks_path)
        if task_file is None:
            state.phase = "analyze"
            _save_state(project_root, state)
            print("没有合法的 tasks.json，已停止，未继续写代码。", file=sys.stderr)
            return 2

        nxt = select_next_task(task_file.tasks)
        if nxt.kind == "done":
            return 0
        if nxt.kind == "blocked" and nxt.task is not None:
            state.phase = "implement"
            state.current_task_id = nxt.task.id
            _save_state(project_root, state)
            reason = nxt.task.blocked_reason or "未写明原因"
            print(f"任务 {nxt.task.id} 已阻塞：{reason}", file=sys.stderr)
            print(_resume_hint(project_root, state.slug), file=sys.stderr)
            return 2
        if nxt.kind == "waiting" and nxt.task is not None:
            state.phase = "implement"
            state.current_task_id = nxt.task.id
            _save_state(project_root, state)
            waiting = unmet_dependencies(nxt.task, task_file.tasks)
            detail = f"（还差：{'、'.join(waiting)}）" if waiting else ""
            print(f"任务 {nxt.task.id} 的依赖无法满足{detail}，已停止。", file=sys.stderr)
            return 2
        if nxt.task is None:
            print("没有可执行的任务，已停止。", file=sys.stderr)
            return 2

        state.phase = "implement"
        state.current_task_id = nxt.task.id
        _save_state(project_root, state)
        write_task_file(tasks_path, mark_task_in_progress(task_file, nxt.task.id))
        retry_label = "（重试）" if nxt.retry else ""
        print(f"[任务 {nxt.task.id}] 开始{retry_label}", file=sys.stderr)
        code = _send(
            agent,
            project_root,
            state,
            strategy.implement_prompt(
                _prompt_context(project_root, state, project),
                nxt.task,
                nxt.retry or bool(nxt.task.blocked_reason),
            ),
        )
        if code != 0:
            return code

        updated_file = read_task_file(tasks_path)
        updated = None
        if updated_file is not None:
            updated = next((task for task in updated_file.tasks if task.id == nxt.task.id), None)
        if updated is None or updated.status != "done":
            state.phase = "implement"
            _save_state(project_root, state)
            status = updated.status if updated is not None else "缺失"
            print(f"任务 {nxt.task.id} 结束后状态为 {status}，已停止。", file=sys.stderr)
            print(_resume_hint(project_root, state.slug), file=sys.stderr)
            return 2


def _run_document(
    agent: Any,
    project_root: str,
    state: RunState,
    project: ProjectProfile,
    strategy: ModeStrategy,
) -> int:
    task_file = read_task_file(_tasks_file(project_root, state.slug))
    if task_file is None or select_next_task(task_file.tasks).kind != "done":
        print("还有未完成的任务，不写功能说明。", file=sys.stderr)
        return 2
    print("[功能说明] 开始", file=sys.stderr)
    return _send(agent, project_root, state, strategy.document_prompt(_prompt_context(project_root, state, project)))


def _send_plain(agent: Any, prompt: str) -> int:
    return _send(agent, None, None, prompt)


def _send(agent: Any, project_root: str | None, state: RunState | None, prompt: str) -> int:
    try:
        run = agent.send(prompt)
        print(f"agentId={agent.agent_id} run.id={run.id}", flush=True)
        if state is not None and project_root is not None:
            state.last_run_id = run.id
            _save_state(project_root, state)

        can_stream = bool(run.supports("stream") or run.supports("messages"))
        try:
            if can_stream:
                for message in run.messages():
                    _write_stream_event(message)
                sys.stdout.write("\n")
                sys.stdout.flush()
        finally:
            result = run.wait()
        result_id = _result_id(result, run)
        if result.status == "error":
            print(f"运行失败：{result_id}{_result_error_suffix(result)}", file=sys.stderr)
            return 2
        if result.status == "cancelled":
            print(f"运行已取消：{result_id}", file=sys.stderr)
            return 2
        if not can_stream and getattr(result, "result", None):
            sys.stdout.write(f"{result.result}\n")
            sys.stdout.flush()
        return 0
    except CursorAgentError as error:
        return _handle_startup_error(error)


def _write_stream_event(event: object) -> None:
    event_type = _field(event, "type")
    if event_type == "assistant":
        message = _field(event, "message")
        content = _field(message, "content") if message is not None else None
        if content is None:
            return
        for block in content:
            if _field(block, "type") == "text":
                text = _field(block, "text")
                if isinstance(text, str):
                    sys.stdout.write(text)
                    sys.stdout.flush()
        return
    if event_type == "tool_call" and _field(event, "status") == "running":
        name = _field(event, "name")
        sys.stderr.write(f"[tool] {name}\n")
        sys.stderr.flush()


def _reopen_if_needed(project_root: str, state: RunState) -> None:
    if not state.current_task_id:
        return
    tasks_path = _tasks_file(project_root, state.slug)
    task_file = read_task_file(tasks_path)
    if task_file is None:
        return
    updated = reopen_blocked_task(task_file, state.current_task_id)
    if updated is not None:
        write_task_file(tasks_path, updated)


def _all_tasks_done(project_root: str, slug: str) -> bool:
    task_file = read_task_file(_tasks_file(project_root, slug))
    if task_file is None:
        return False
    return select_next_task(task_file.tasks).kind == "done"


def _prompt_context(project_root: str, state: RunState, project: ProjectProfile) -> PromptContext:
    full_config = load_workflow_config(project_root)
    mcp = full_config.unity_mcp
    kb_map = knowledge_map_path(full_config, project_root) or ""
    mcp_server = mcp.server if mcp.enabled and mcp_server_entry(mcp) is not None else ""
    skill_name = "indie-feature" if state.mode == "indie" else "work-feature"
    plan = _framework_plan(project_root, state)
    return PromptContext(
        feature=state.feature,
        slug=state.slug,
        design_path=to_project_path(project_root, state.design_path),
        prefab_paths=[to_project_path(project_root, item) for item in state.prefabs],
        tasks_path=to_project_path(project_root, str(_tasks_file(project_root, state.slug))),
        dev_spec_enabled=state.dev_spec_enabled,
        feature_doc_enabled=state.feature_doc_enabled,
        dev_spec_path=to_project_path(project_root, state.dev_spec_path),
        feature_doc_path=to_project_path(project_root, state.feature_doc_path),
        constraints=format_project_constraints(project, kb_map, skill_name),
        protected_paths=list(project.protected_paths),
        unity_mcp_server=mcp_server,
        knowledge_root=full_config.knowledge.root,
        knowledge_map=kb_map,
        mode=state.mode,
        game=state.game or state.slug,
        framework_enabled=state.framework_enabled,
        framework_plan_path=to_project_path(project_root, state.framework_plan_path) if state.framework_plan_path else "",
        framework_doc_path=to_project_path(project_root, state.framework_doc_path) if state.framework_doc_path else "",
        framework_doc_enabled=state.framework_doc_enabled,
        framework_summary=plan_summary(plan) if plan is not None else "",
        framework_hooks=hook_aliases(plan) if plan is not None else "",
        framework_paradigm=full_config.framework.paradigm,
        flow_enabled=state.flow_enabled and state.mode == "work",
        flow_path=to_project_path(project_root, state.flow_path) if state.flow_path else "",
        project_root=project_root,
    )


def _framework_plan(project_root: str, state: RunState) -> Any:
    if not state.framework_enabled or not state.framework_plan_path:
        return None
    return read_framework_plan(state.framework_plan_path)


def _handle_startup_error(error: CursorAgentError) -> int:
    retryable = str(getattr(error, "is_retryable", False)).lower()
    message = getattr(error, "message", None) or str(error)
    print(f"启动失败：{message}，可重试={retryable}", file=sys.stderr)
    return 1


def _unity_check(project_root: str) -> int:
    if is_unity_project(project_root):
        return 0
    print(f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {project_root}", file=sys.stderr)
    return 1


def _ensure_skill(project_root: str, skill_dir: str) -> int:
    skill = Path(project_root) / skill_dir / "SKILL.md"
    if skill.exists():
        return 0
    print(f"工程里还没有 {Path(skill_dir).name} Skill。请先执行 bulings init --project <Unity工程>", file=sys.stderr)
    return 1


def _require_api_key() -> str | None:
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if api_key:
        return api_key
    print("缺少环境变量 CURSOR_API_KEY。在 Cursor Dashboard → Integrations 创建用户 API key。", file=sys.stderr)
    return None


def _resolve_existing_file(input_path: str, project_root: str) -> str:
    candidates = [
        os.path.abspath(input_path),
        os.path.abspath(os.path.join(project_root, input_path)),
    ]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normpath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(normalized):
            return normalized
    raise RuntimeError(f"找不到文件: {input_path}")


def _warn_if_not_prefab(file_path: str) -> None:
    if not file_path.lower().endswith(".prefab"):
        print(f"警告：{file_path} 不是 .prefab 文件，仍会交给分析。", file=sys.stderr)


def _run_directory(project_root: str, slug: str) -> Path:
    return Path(project_root) / ".bulings" / "runs" / slug


def _tasks_file(project_root: str, slug: str) -> Path:
    return _run_directory(project_root, slug) / "tasks.json"


def _state_path(project_root: str, slug: str) -> Path:
    return _run_directory(project_root, slug) / "state.json"


def _resume_hint(project_root: str, slug: str) -> str:
    return f'bulings resume --project "{project_root}" --run {slug}'


def _save_state(project_root: str, state: RunState) -> None:
    target = _state_path(project_root, state.slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(_state_to_dict(state), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_state(file_path: Path) -> RunState | None:
    if not file_path.exists():
        return None
    try:
        parsed = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if not isinstance(parsed.get("slug"), str) or not isinstance(parsed.get("phase"), str):
        return None
    prefabs = parsed.get("prefabs")
    return RunState(
        agent_id=parsed.get("agentId") if isinstance(parsed.get("agentId"), str) else None,
        slug=parsed["slug"],
        feature=parsed["feature"] if isinstance(parsed.get("feature"), str) else parsed["slug"],
        design_path=parsed["designPath"] if isinstance(parsed.get("designPath"), str) else "",
        prefabs=[item for item in prefabs if isinstance(item, str)] if isinstance(prefabs, list) else [],
        dev_spec_enabled=parsed.get("devSpecEnabled") if isinstance(parsed.get("devSpecEnabled"), bool) else False,
        feature_doc_enabled=parsed.get("featureDocEnabled") if isinstance(parsed.get("featureDocEnabled"), bool) else False,
        dev_spec_path=parsed["devSpecPath"] if isinstance(parsed.get("devSpecPath"), str) else "",
        feature_doc_path=parsed["featureDocPath"] if isinstance(parsed.get("featureDocPath"), str) else "",
        model=parsed["model"] if isinstance(parsed.get("model"), str) else "",
        phase=parsed["phase"],
        current_task_id=parsed.get("currentTaskId") if isinstance(parsed.get("currentTaskId"), str) else None,
        last_run_id=parsed.get("lastRunId") if isinstance(parsed.get("lastRunId"), str) else None,
        mode=parsed["mode"] if isinstance(parsed.get("mode"), str) else "work",
        game=parsed["game"] if isinstance(parsed.get("game"), str) else "",
        framework_enabled=parsed.get("frameworkEnabled") if isinstance(parsed.get("frameworkEnabled"), bool) else False,
        framework_plan_path=parsed["frameworkPlanPath"] if isinstance(parsed.get("frameworkPlanPath"), str) else "",
        framework_doc_path=parsed["frameworkDocPath"] if isinstance(parsed.get("frameworkDocPath"), str) else "",
        framework_doc_enabled=parsed.get("frameworkDocEnabled")
        if isinstance(parsed.get("frameworkDocEnabled"), bool)
        else True,
        flow_enabled=parsed.get("flowEnabled") if isinstance(parsed.get("flowEnabled"), bool) else True,
        flow_path=parsed["flowPath"] if isinstance(parsed.get("flowPath"), str) else "",
    )


def _state_to_dict(state: RunState) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if state.agent_id:
        data["agentId"] = state.agent_id
    data["slug"] = state.slug
    data["feature"] = state.feature
    data["designPath"] = state.design_path
    data["prefabs"] = list(state.prefabs)
    data["devSpecEnabled"] = state.dev_spec_enabled
    data["featureDocEnabled"] = state.feature_doc_enabled
    data["devSpecPath"] = state.dev_spec_path
    data["featureDocPath"] = state.feature_doc_path
    data["model"] = state.model
    data["phase"] = state.phase
    data["mode"] = state.mode
    if state.game:
        data["game"] = state.game
    data["frameworkEnabled"] = state.framework_enabled
    if state.framework_plan_path:
        data["frameworkPlanPath"] = state.framework_plan_path
    if state.framework_doc_path:
        data["frameworkDocPath"] = state.framework_doc_path
    data["frameworkDocEnabled"] = state.framework_doc_enabled
    data["flowEnabled"] = state.flow_enabled
    if state.flow_path:
        data["flowPath"] = state.flow_path
    if state.current_task_id:
        data["currentTaskId"] = state.current_task_id
    if state.last_run_id:
        data["lastRunId"] = state.last_run_id
    return data


def _field(obj: object, name: str) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name)
    return getattr(obj, name, None)


def _result_id(result: object, run: object) -> str:
    for source in (result, run):
        value = getattr(source, "id", None)
        if isinstance(value, str) and value:
            return value
    return ""


def _result_error_suffix(result: object) -> str:
    error = _field(result, "error")
    if isinstance(error, str):
        message: object = error
    elif error is None:
        message = None
    else:
        message = _field(error, "message")
    if not isinstance(message, str) or message == "":
        message = _field(result, "error_message")
    if isinstance(message, str) and message:
        return f" {message}"
    return ""
