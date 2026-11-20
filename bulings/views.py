"""只读视图：`bulings status`、`bulings doctor`、`bulings design --history` 的数据整理。

这些函数只读 `.bulings/`、策划案和代码状态，不启动 Agent、不写文件。
``runner`` 负责把结果打到终端，这里只负责把散在各处的产物拼成一份结构。
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from bulings.config import WorkflowConfig, game_token, to_project_path
from bulings.framework import (
    FrameworkPlan,
    framework_drift,
    framework_ready,
    read_framework_plan,
)
from bulings.gdd import (
    design_round_snapshot_path,
    dimension_title,
    pending_dimensions,
    read_gdd_plan,
    stage_title,
)
from bulings.tasks import read_task_file


@dataclass
class DesignView:
    slug: str
    round: int
    stage: str
    status: str
    confirmed: int
    dimensions: int
    doc_path: str
    pending: list[str] = field(default_factory=list)


@dataclass
class FrameworkView:
    enabled: bool
    ready: bool
    plan_path: str
    doc_path: str
    doc_exists: bool = False
    systems: int = 0
    pending_systems: int = 0
    extension_points: int = 0
    drift: list[str] = field(default_factory=list)


@dataclass
class RunView:
    slug: str
    phase: str
    done: int = 0
    total: int = 0
    blocked: list[dict[str, str]] = field(default_factory=list)


@dataclass
class StatusView:
    mode: str
    game: str
    designs: list[DesignView] = field(default_factory=list)
    framework: FrameworkView | None = None
    runs: list[RunView] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


@dataclass
class CheckItem:
    level: str
    title: str
    detail: str = ""


# ---------- status ----------


def build_status(
    project_root: str,
    config: WorkflowConfig,
    plan: FrameworkPlan | None = None,
) -> StatusView:
    view = StatusView(mode=config.mode, game=game_token(project_root))
    view.designs = _design_views(project_root, config)
    view.framework = _framework_view(project_root, config, plan)
    view.runs = _run_views(project_root)
    view.next_steps = _next_steps(view)
    return view


def status_lines(view: StatusView) -> list[str]:
    lines = [f"模式：{view.mode}    工程：{view.game}"]
    lines += _design_lines(view)
    lines += _framework_lines(view)
    lines += _run_lines(view)
    if view.next_steps:
        lines.append("")
        for item in view.next_steps:
            lines.append(f"下一步：{item}")
    return lines


def status_json(view: StatusView) -> str:
    """`--json` 的机器可读版本。"""
    import json

    payload = {
        "mode": view.mode,
        "game": view.game,
        "designs": [
            {
                "slug": item.slug,
                "round": item.round,
                "stage": item.stage,
                "status": item.status,
                "confirmed": item.confirmed,
                "dimensions": item.dimensions,
                "pending": item.pending,
                "docPath": item.doc_path,
            }
            for item in view.designs
        ],
        "framework": None
        if view.framework is None
        else {
            "enabled": view.framework.enabled,
            "ready": view.framework.ready,
            "planPath": view.framework.plan_path,
            "docPath": view.framework.doc_path,
            "docExists": view.framework.doc_exists,
            "systems": view.framework.systems,
            "pendingSystems": view.framework.pending_systems,
            "extensionPoints": view.framework.extension_points,
            "drift": view.framework.drift,
        },
        "runs": [
            {"slug": item.slug, "phase": item.phase, "done": item.done, "total": item.total, "blocked": item.blocked}
            for item in view.runs
        ],
        "nextSteps": view.next_steps,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _design_views(project_root: str, config: WorkflowConfig) -> list[DesignView]:
    root = Path(project_root) / ".bulings" / "design"
    if not root.is_dir():
        return []
    views: list[DesignView] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        plan = read_gdd_plan(entry / "design.json")
        if plan is None:
            continue
        pending = pending_dimensions(plan)
        doc_path = to_project_path(project_root, _resolve(project_root, config.design.path.replace("{feature}", plan.slug)))
        views.append(
            DesignView(
                slug=plan.slug,
                round=plan.round,
                stage=stage_title(plan.stage),
                status=plan.status,
                confirmed=4 - len(pending),
                dimensions=4,
                doc_path=doc_path,
                pending=pending,
            )
        )
    return views


def _framework_view(project_root: str, config: WorkflowConfig, plan: FrameworkPlan | None) -> FrameworkView | None:
    if config.mode != "indie" and not config.framework.enabled:
        return None
    plan_path = _resolve(project_root, config.framework.plan)
    if plan is None and config.framework.enabled:
        plan = read_framework_plan(plan_path)
    doc_abs = _resolve(project_root, config.framework.doc.replace("{game}", game_token(project_root)))
    view = FrameworkView(
        enabled=config.framework.enabled,
        ready=framework_ready(plan),
        plan_path=to_project_path(project_root, plan_path),
        doc_path=to_project_path(project_root, doc_abs),
        doc_exists=os.path.isfile(doc_abs),
    )
    if plan is not None:
        view.systems = len(plan.systems)
        view.pending_systems = sum(1 for system in plan.systems if system.status == "pending")
        view.extension_points = len(plan.extension_points)
        view.drift = framework_drift(plan, project_root)
    return view


def _run_views(project_root: str) -> list[RunView]:
    root = Path(project_root) / ".bulings" / "runs"
    if not root.is_dir():
        return []
    views: list[RunView] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        view = RunView(slug=entry.name, phase=_read_phase(entry / "state.json"))
        tasks = read_task_file(entry / "tasks.json")
        if tasks is not None:
            view.total = len(tasks.tasks)
            view.done = sum(1 for task in tasks.tasks if task.status == "done")
            view.blocked = [
                {"id": task.id, "reason": task.blocked_reason or "未写明原因"}
                for task in tasks.tasks
                if task.status == "blocked"
            ]
        views.append(view)
    return views


def _read_phase(path: Path) -> str:
    import json

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return "unknown"
    if isinstance(parsed, dict) and isinstance(parsed.get("phase"), str):
        return parsed["phase"]
    return "unknown"


def _design_lines(view: StatusView) -> list[str]:
    if not view.designs:
        return ["策划案：还没有"]
    lines = ["策划案："]
    for item in view.designs:
        state = "已定稿" if item.status == "done" else "迭代中"
        lines.append(
            f"  {item.slug}：第 {item.round} 轮 · {item.stage} · {state}"
            f"（维度 {item.confirmed}/{item.dimensions}）"
        )
        lines.append(f"    正文：{item.doc_path}")
        if item.pending:
            names = "、".join(dimension_title(name) for name in item.pending)
            lines.append(f"    待确认维度：{names}")
    return lines


def _framework_lines(view: StatusView) -> list[str]:
    framework = view.framework
    if framework is None:
        return []
    if not framework.enabled:
        return ["框架：已关闭（--no-framework 或 indie.framework.enabled: false）"]
    state = "就绪" if framework.ready else "未就绪"
    lines = [
        f"框架：{state}（{framework.systems} 个系统，{framework.pending_systems} 个 pending，"
        f"{framework.extension_points} 个扩展点）"
    ]
    lines.append(f"  清单：{framework.plan_path}")
    if not framework.doc_exists:
        lines.append(f"  框架文档缺失：{framework.doc_path}")
    for item in framework.drift[:5]:
        lines.append(f"  ⚠ 磁盘上找不到：{item}")
    if len(framework.drift) > 5:
        lines.append(f"  ⚠ 还有 {len(framework.drift) - 5} 条漂移")
    return lines


def _run_lines(view: StatusView) -> list[str]:
    if not view.runs:
        return ["运行：还没有"]
    lines = ["运行："]
    for item in view.runs:
        lines.append(f"  {item.slug}：{item.phase}（任务 {item.done}/{item.total}）")
        for blocked in item.blocked:
            lines.append(f"    阻断 {blocked['id']}：{blocked['reason']}")
    return lines


def _next_steps(view: StatusView) -> list[str]:
    steps: list[str] = []
    ready_design = next((item for item in view.designs if item.status == "done"), None)
    if ready_design is not None:
        steps.append(f"bulings run --project <工程> --design {ready_design.doc_path}")
    unfinished = next((item for item in view.designs if item.status != "done"), None)
    if unfinished is not None:
        steps.append(f"bulings design --project <工程> --name {unfinished.slug} --decide <id>")
    if view.framework is not None and view.framework.enabled and not view.framework.ready:
        steps.append("先补齐框架阶段（framework.json 的 status 改成 done），再 run")
    for run in view.runs:
        if run.blocked:
            steps.append(f"补齐阻断项后：bulings resume --project <工程> --run {run.slug}")
    return steps[:2]


def _resolve(project_root: str, pattern: str) -> str:
    if os.path.isabs(pattern):
        return os.path.normpath(pattern)
    return os.path.normpath(os.path.join(os.path.abspath(project_root), pattern))


# ---------- history ----------


def design_history(project_root: str, slug: str) -> list[dict]:
    snapshot_dir = design_round_snapshot_path(project_root, slug, 0).parent
    if not snapshot_dir.is_dir():
        return []
    items: list[dict] = []
    for path in sorted(snapshot_dir.glob("*.json"), key=lambda item: _round_sort_key(item.stem)):
        plan = read_gdd_plan(path)
        item: dict = {"round": path.stem, "recorded": plan is not None}
        if plan is None:
            item.update({"stage": "-", "status": "-", "options": [], "decision": []})
        else:
            item.update(
                {
                    "round": plan.round,
                    "stage": stage_title(plan.stage),
                    "status": plan.status,
                    "options": [option.id for option in plan.options],
                    "decision": [ids for decision in plan.chosen if decision.round == plan.round for ids in decision.ids],
                }
            )
        items.append(item)
    return items


def history_lines(slug: str, rounds: list[dict]) -> list[str]:
    if not rounds:
        return [f"{slug} 还没有轮次快照（从下一轮开始记录：.bulings/design/{slug}/rounds/）。"]
    lines = [f"{slug} 的轮次历史："]
    for item in rounds:
        options = "、".join(item["options"]) or "无"
        chosen = "（快照缺失）" if not item["recorded"] else ("、".join(item["decision"]) or "仅补充说明")
        lines.append(f"  第 {item['round']} 轮  阶段 {item['stage']}  状态 {item['status']}")
        lines.append(f"    选项：{options}")
        lines.append(f"    选择：{chosen}")
    return lines


def _round_sort_key(stem: str) -> tuple[int, str]:
    return (int(stem), "") if stem.isdigit() else (10**9, stem)


# ---------- doctor ----------


def doctor_checks(project_root: str, config: WorkflowConfig | None) -> list[CheckItem]:
    items: list[CheckItem] = []
    root = Path(project_root)
    unity = (root / "Assets").is_dir() and (root / "ProjectSettings").is_dir()
    items.append(
        CheckItem("ok" if unity else "fail", "Unity 工程", "找到 Assets 和 ProjectSettings" if unity else "缺少 Assets 或 ProjectSettings")
    )
    if config is None:
        items.append(CheckItem("fail", "workflow.yaml", "解析失败，检查 YAML 写法"))
        return items
    items.append(CheckItem("ok", "workflow.yaml", f"mode: {config.mode}"))

    skill = root / ".cursor" / "skills" / ("indie-feature" if config.mode == "indie" else "work-feature") / "SKILL.md"
    items.append(
        CheckItem("ok" if skill.is_file() else "warn", "Skill 已安装", str(skill) if skill.is_file() else "先跑 bulings init")
    )

    key = os.environ.get("CURSOR_API_KEY", "").strip()
    items.append(CheckItem("ok" if key else "warn", "CURSOR_API_KEY", "已设置" if key else "未设置，命令行跑不起来"))

    if not config.unity_mcp.enabled:
        items.append(CheckItem("ok", "Unity MCP", "已关闭"))
    else:
        target = config.unity_mcp.url
        reachable, detail = _probe(target) if target else (False, "未配置 url")
        items.append(CheckItem("ok" if reachable else "warn", "Unity MCP", detail))

    if config.mode == "indie":
        plan_path = _resolve(project_root, config.framework.plan)
        plan = read_framework_plan(plan_path)
        ready = framework_ready(plan)
        items.append(
            CheckItem("ok" if ready else "warn", "框架基线", "已就绪" if ready else "未就绪或不存在，run 会先建框架")
        )
        doc_path = _resolve(project_root, config.framework.doc.replace("{game}", game_token(project_root)))
        if config.framework.doc_enabled:
            items.append(
                CheckItem("ok" if os.path.isfile(doc_path) else "warn", "框架文档", str(doc_path))
            )
        docs_dir = _resolve(project_root, config.design.path.replace("{feature}", "demo")).rsplit(os.sep, 1)[0]
        writable = os.path.isdir(docs_dir) or os.access(os.path.dirname(docs_dir) or ".", os.W_OK)
        items.append(CheckItem("ok" if writable else "warn", "策划案目录可写", docs_dir))
    return items


def doctor_lines(items: list[CheckItem]) -> list[str]:
    lines = []
    marks = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    for item in items:
        mark = marks.get(item.level, item.level.upper())
        detail = f"：{item.detail}" if item.detail else ""
        lines.append(f"[{mark}] {item.title}{detail}")
    return lines


def _probe(url: str) -> tuple[bool, str]:
    """只做一次 1 秒内的 TCP 连接，不碰 MCP 协议。"""
    parsed = urlparse(url if "://" in url else f"http://{url}")
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return False, f"解析不出主机：{url}"
    try:
        with socket.create_connection((host, port), timeout=1):
            return True, f"{host}:{port} 可达"
    except OSError as error:
        return False, f"{host}:{port} 连不上（{error.strerror or error}）"
