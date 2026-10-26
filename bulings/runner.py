from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

from bulings.config import (
    ProjectProfile,
    RunOverrides,
    feature_from_design,
    feature_token,
    load_workflow_config,
    resolve_run_config,
    to_project_path,
)
from bulings.install import is_unity_project
from bulings.prompts import (
    PromptContext,
    analyze_prompt,
    document_prompt,
    format_project_constraints,
    implement_prompt,
)
from bulings.tasks import (
    mark_task_in_progress,
    read_task_file,
    reopen_blocked_task,
    select_next_task,
    write_task_file,
)

INDEPENDENT_BLOCK_NOTE = "还有不依赖阻塞项的任务会先做。轮到阻塞项时停下，确认后用 resume 重试。"


@dataclass
class RunCommand:
    project: str
    design: str
    prefabs: list[str]
    name: str | None
    overrides: RunOverrides


@dataclass
class ResumeCommand:
    project: str
    slug: str


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


def run_workflow(command: RunCommand) -> int:
    project_root = os.path.abspath(command.project)
    unity_error = _unity_check(project_root)
    if unity_error != 0:
        return unity_error

    config = load_workflow_config(project_root)
    if config.mode == "indie":
        return _indie_stop()

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
    )

    existing = _read_state(_state_path(project_root, state.slug))
    if existing is not None and existing.phase != "done":
        print(
            f"已有未完成的运行 {state.slug}。继续请执行：\n{_resume_hint(project_root, state.slug)}",
            file=sys.stderr,
        )
        return 1

    if _ensure_skill(project_root) != 0:
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
            return _drive(agent, project_root, state, config.project, False)
    except CursorAgentError as error:
        return _handle_startup_error(error)


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
    if config.mode == "indie":
        return _indie_stop()

    if _ensure_skill(project_root) != 0:
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
            return _drive(agent, project_root, state, config.project, True)
    except CursorAgentError as error:
        return _handle_startup_error(error)


def _drive(
    agent: Any,
    project_root: str,
    state: RunState,
    project: ProjectProfile,
    resuming: bool,
) -> int:
    if state.phase == "analyze":
        analyzed = _run_analyze(agent, project_root, state, project)
        if analyzed != 0:
            return analyzed
        resuming = False

    if state.phase == "document" and not _all_tasks_done(project_root, state.slug):
        state.phase = "implement"

    if state.phase == "implement":
        if resuming:
            _reopen_if_needed(project_root, state)
        implemented = _run_implement(agent, project_root, state, project)
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
    documented = _run_document(agent, project_root, state, project)
    if documented != 0:
        return documented

    state.phase = "done"
    _save_state(project_root, state)
    print(f"功能说明已写入 {to_project_path(project_root, state.feature_doc_path)}")
    return 0


def _run_analyze(agent: Any, project_root: str, state: RunState, project: ProjectProfile) -> int:
    _run_directory(project_root, state.slug).mkdir(parents=True, exist_ok=True)
    print("[分析] 开始", file=sys.stderr)
    code = _send(agent, project_root, state, analyze_prompt(_prompt_context(project_root, state, project)))
    if code != 0:
        return code

    tasks = read_task_file(_tasks_file(project_root, state.slug))
    if tasks is None:
        state.phase = "analyze"
        _save_state(project_root, state)
        print("分析结束但没有合法的 tasks.json，已停止，未进入写代码。", file=sys.stderr)
        return 2

    state.phase = "implement"
    _save_state(project_root, state)
    if any(task.status == "blocked" for task in tasks.tasks):
        print(INDEPENDENT_BLOCK_NOTE, file=sys.stderr)
    return 0


def _run_implement(agent: Any, project_root: str, state: RunState, project: ProjectProfile) -> int:
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
            print(f"任务 {nxt.task.id} 的依赖无法满足，已停止。", file=sys.stderr)
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
            implement_prompt(
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


def _run_document(agent: Any, project_root: str, state: RunState, project: ProjectProfile) -> int:
    task_file = read_task_file(_tasks_file(project_root, state.slug))
    if task_file is None or select_next_task(task_file.tasks).kind != "done":
        print("还有未完成的任务，不写功能说明。", file=sys.stderr)
        return 2
    print("[功能说明] 开始", file=sys.stderr)
    return _send(agent, project_root, state, document_prompt(_prompt_context(project_root, state, project)))


def _send(agent: Any, project_root: str, state: RunState, prompt: str) -> int:
    try:
        run = agent.send(prompt)
        print(f"agentId={agent.agent_id} run.id={run.id}", flush=True)
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
        constraints=format_project_constraints(project),
        protected_paths=list(project.protected_paths),
    )


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


def _indie_stop() -> int:
    print("独游模式本版本未实现，停止，不要擅自开工。", file=sys.stderr)
    return 1


def _ensure_skill(project_root: str) -> int:
    skill = Path(project_root) / ".cursor" / "skills" / "work-feature" / "SKILL.md"
    if skill.exists():
        return 0
    print("工程里还没有工作模式 Skill。请先执行 bulings init --project <Unity工程>", file=sys.stderr)
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
