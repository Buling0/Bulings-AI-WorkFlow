"""独游模式：先立框架，再按纵向切片做功能。

和工作模式的差别只有两处，都收在这里：
1. 正式写功能之前先过一道``框架阶段``（:func:`prepare`），把可扩展的最小框架落地；
2. 拆出来的每项任务必须写明挂在哪个框架扩展点上（:func:`validate_indie_tasks`）。
"""

from __future__ import annotations

import os
import sys

from bulings.framework import (
    NEW_HOOK_PREFIX,
    FrameworkPlan,
    framework_drift,
    framework_ready,
    hook_aliases,
    known_hooks,
    plan_summary,
    read_framework_plan,
)
from bulings.modes.base import INDIE_SKILL_DIR, ModeEnv, ModeStrategy
from bulings.prompts import PromptContext
from bulings.tasks import FeatureTask, TaskFile

SKILL = INDIE_SKILL_DIR


def indie_strategy(context: PromptContext) -> ModeStrategy:
    return ModeStrategy(
        name="indie",
        skill_dir=INDIE_SKILL_DIR,
        requires_prefab=False,
        analyze_prompt=lambda ctx: indie_analyze_prompt(ctx),
        implement_prompt=indie_implement_prompt,
        document_prompt=lambda ctx: indie_document_prompt(ctx),
        prepare=prepare,
        validate_tasks=validate_indie_tasks,
    )


def _skill(path: str) -> str:
    return f"{SKILL}/{path}"


def _absolute(project_root: str, path: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(project_root, path))


def _load_plan(context: PromptContext, project_root: str = "") -> FrameworkPlan | None:
    if not context.framework_enabled or not context.framework_plan_path:
        return None
    root = project_root or context.project_root
    return read_framework_plan(_absolute(root, context.framework_plan_path))


def _paradigm_line(context: PromptContext) -> str:
    if context.framework_paradigm:
        return f"范式要求（workflow.yaml 指定）：{context.framework_paradigm}"
    return (
        "范式要求：未指定。按 frameworks.md 选型，默认用零外部依赖的轻量自建基线；"
        "工程里已有范式时优先服从工程。"
    )


def _framework_lines(context: PromptContext) -> list[str]:
    if not context.framework_enabled:
        return ["框架基线：已关闭（--no-framework 或 indie.framework.enabled 为 false）。"]
    if context.framework_summary:
        return [f"框架基线（来自 {context.framework_plan_path}）：", context.framework_summary]
    return [f"框架基线：还没有（{context.framework_plan_path} 待建立）。"]


def framework_prompt(context: PromptContext, draft_summary: str, drift: list[str]) -> str:
    lines = [
        f"先阅读 {_skill('SKILL.md')}，只执行其中的「建立框架」阶段。",
        f"再读 {_skill('frameworks.md')}（选型与最小基线）和 {_skill('framework-template.md')}（产物格式）。",
        "这一阶段只立框架：不实现具体玩法功能，不建 tasks.json，不写功能说明。",
        "",
        f"工程 / 游戏：{context.game}",
        f"策划案：{context.design_path}",
        f"框架清单（必须写入）：{context.framework_plan_path}",
        f"框架文档（必须写入）：{context.framework_doc_path}",
        "预制体（可空，只用来了解现有表现层）：",
        *([f"- {item}" for item in context.prefab_paths] or ["- 无"]),
        "",
        "项目约束：",
        context.constraints,
        "",
        _paradigm_line(context),
        *_mcp_lines(context),
    ]
    if draft_summary:
        lines += [
            "",
            "已有框架草稿。只补没做完的部分，不要重建已经落地的系统：",
            draft_summary,
        ]
    if drift:
        lines += ["", "这些登记过的路径在磁盘上已经找不到，先修登记或补文件：", *[f"- {item}" for item in drift]]
    lines += [
        "",
        "完成标准：",
        f"1. {context.framework_plan_path} 通过校验：game、paradigm、root 非空；systems 至少一项；status 只有全部系统可运行才写 done。",
        "2. systems 里每一项都有 title、paths、status；extensionPoints 至少列出「怎么加新状态 / 新事件 / 新配置 / 新存档字段」。",
        f"3. {context.framework_doc_path} 写清分层、目录与程序集、各系统入口、扩展点清单、约定与反模式。",
        "4. 代码骨架不留空壳：每个类都有真实职责，能跑通一个最小的启动到退出回路；不改 protectedPaths。",
        "",
        _protected_line(context.protected_paths),
        "不要创建 git commit。不要修改 .meta 的 guid。不要引入需要联网安装的第三方包。",
    ]
    return "\n".join(line for line in lines if line != "")


def indie_analyze_prompt(context: PromptContext) -> str:
    plan = _load_plan(context)
    hooks = hook_aliases(plan) if plan is not None else ""
    prefabs = "\n".join(f"- {item}" for item in context.prefab_paths) or "- 无"
    if context.dev_spec_enabled:
        dev_spec = f"开发说明：写入 {context.dev_spec_path}，按 {_skill('slice-spec-template.md')}。"
    else:
        dev_spec = "开发说明：不要生成。"
    lines = [
        f"先阅读 {_skill('SKILL.md')}，只执行其中的「拆切片」阶段。",
        "不要写玩法代码，不要实现任务，不要写功能说明。",
        "",
        f"功能名：{context.feature}",
        f"策划案：{context.design_path}",
        "预制体（可空）：",
        prefabs,
        f"任务文件（必须写入）：{context.tasks_path}",
        dev_spec,
        "",
        *_framework_lines(context),
        "",
        "项目约束：",
        context.constraints,
        "",
        "拆法：按纵向切片，一项任务 = 一条能独立验收的能力。数据、逻辑、表现、接线尽量留在同一切片里，"
        "不要按「先做数据层再做界面」这种技术层切。",
    ]
    if plan is not None:
        lines += [
            f"每项任务都要写 framework，取值只能来自这份挂载点清单：{hooks}。",
            f"需要框架里还没有的扩展点时，写 \"{NEW_HOOK_PREFIX} <一句话说明>\"，实现阶段再登记进框架清单。",
        ]
    else:
        lines += [
            "框架基线不可用。每项任务的 framework 仍要写清楚它依赖或新增的扩展点，"
            f"新增的写 \"{NEW_HOOK_PREFIX} <说明>\"。",
        ]
    lines += [
        "同一能力的任务用同一个 slice 名；dependsOn 写真实前置。",
        _protected_line(context.protected_paths),
        "不要创建 git commit。不要修改 .meta 的 guid。不要启动 Unity 批处理编译。",
        "tasks.json 的 status 只能是 pending、in_progress、done、blocked；至少一项任务；id 不要重复。",
        "策划和工程对不上时，该项 status 为 blocked，并写 blockedReason。",
    ]
    return "\n".join(line for line in lines if line != "")


def indie_implement_prompt(context: PromptContext, task: FeatureTask, retry: bool) -> str:
    retry_line = (
        "这是中断后的重做，或这项上次已阻塞。只修补这一项，不要重做已经 done 的任务。"
        if retry
        else "这是第一次实现这项。"
    )
    reason = f"上次阻塞原因：{task.blocked_reason}" if task.blocked_reason else ""
    if context.dev_spec_enabled:
        dev_spec = f"若存在开发说明 {context.dev_spec_path}，同步勾选和状态。"
    else:
        dev_spec = "不要生成开发说明。"
    acceptance = "；".join(task.acceptance) or "与目标一致"
    hooks = "、".join(task.framework) or "未写"
    lines = [
        f"先阅读 {_skill('SKILL.md')}，只执行其中的「实现一个切片」阶段。",
        f"本轮只实现任务 {task.id}：{task.title}。不要开始下一个任务，不要写功能说明。",
        retry_line,
        reason,
        f"切片：{task.slice or context.feature}",
        f"挂载的框架点：{hooks}",
        f"目标：{task.goal}",
        f"完成标准：{acceptance}",
        f"任务文件：{context.tasks_path}",
        dev_spec,
        "",
        *_framework_lines(context),
        "",
        "优先复用已有的框架扩展点，不要为这一个切片另造一套事件系统、状态机或配置读取。",
    ]
    if context.framework_enabled and context.framework_plan_path:
        lines.append(
            f"确实需要新扩展点时，在 {context.framework_plan_path} 的 extensionPoints 里追加一项"
            "（name / howTo / path），不要改已有项，也不要把 status 改回 draft。"
        )
    lines += [
        _protected_line(context.protected_paths),
        "做完把该任务标成 done。无法在不脑补的前提下完成时标成 blocked，并写 blockedReason。",
        "不要创建 git commit。不要修改 .meta 的 guid。",
    ]
    return "\n".join(line for line in lines if line != "")


def indie_document_prompt(context: PromptContext) -> str:
    lines = [
        f"先阅读 {_skill('SKILL.md')}，只执行其中的「功能说明」阶段。",
        f"功能说明按 {_skill('feature-doc-template.md')} 写，依据实际改过的代码。",
        "不要再改玩法代码。不要把任务清单再抄一遍。",
        f"功能名：{context.feature}",
        f"策划案：{context.design_path}",
        f"任务文件：{context.tasks_path}",
        f"功能说明写入：{context.feature_doc_path}",
        "写清：功能做什么、入口、主要类型、数据流、挂载的框架点、新增的扩展点、"
        "如何在这个框架上继续扩展、已知限制、和策划不一致的地方。",
    ]
    if context.framework_enabled and context.framework_plan_path:
        lines.append(
            f"如果切片用了 \"{NEW_HOOK_PREFIX}\" 声明的扩展点而 {context.framework_plan_path} 里还没登记，"
            "先在 extensionPoints 里补登记（只追加，别改已有项）。"
        )
    if context.knowledge_map:
        lines.append(
            f"知识库已存在（地图 {context.knowledge_map}）。功能说明写完后，按 .cursor/skills/knowledge-base/SKILL.md 的"
            " update 动作，只更新受本功能影响的知识库页面；无需更新就明说。"
        )
    return "\n".join(lines)


def validate_indie_tasks(task_file: TaskFile, context: PromptContext) -> list[str]:
    """切片必须挂在框架上。返回空列表表示通过。"""
    plan = _load_plan(context)
    if context.framework_enabled and plan is None:
        return [
            f"框架基线缺失或不可读：{context.framework_plan_path}。"
            "先补齐框架阶段，或确认后用 --no-framework 关闭框架要求再跑。",
        ]
    hooks = hook_aliases(plan) if plan is not None else ""
    errors: list[str] = []
    for task in task_file.tasks:
        entries = [entry.strip() for entry in task.framework if entry.strip()]
        if not entries:
            hint = f"（可用：{hooks}；新增写 {NEW_HOOK_PREFIX} <说明>）" if hooks else ""
            errors.append(f"{task.id} 没有写 framework 挂载点{hint}")
            continue
        for entry in entries:
            if entry.startswith(NEW_HOOK_PREFIX):
                if not entry[len(NEW_HOOK_PREFIX) :].strip():
                    errors.append(f"{task.id} 的 {NEW_HOOK_PREFIX} 后面没有写说明")
                continue
            if plan is not None and entry not in known_hooks(plan):
                errors.append(
                    f"{task.id} 的挂载点 {entry} 不在框架里（可用：{hooks}；新增写 {NEW_HOOK_PREFIX} <说明>）"
                )
    return errors


def prepare(env: ModeEnv) -> int:
    """框架阶段：没有可用框架时先建，建完不合法就停在这里。"""
    context = env.context
    if not context.framework_enabled:
        return 0
    plan_path = _absolute(env.project_root, context.framework_plan_path)
    plan = read_framework_plan(plan_path)
    if framework_ready(plan):
        drift = framework_drift(plan, env.project_root) if plan is not None else []
        if drift:
            print("[框架] 登记的文件在磁盘上找不到，先提示：" + "、".join(drift), file=sys.stderr)
        return 0

    draft_summary = plan_summary(plan) if plan is not None else ""
    drift = framework_drift(plan, env.project_root) if plan is not None else []
    print("[框架] 开始", file=sys.stderr)
    code = env.send(framework_prompt(context, draft_summary, drift))
    if code != 0:
        return code
    plan = read_framework_plan(plan_path)
    if not framework_ready(plan):
        print(
            f"框架阶段结束，但 {context.framework_plan_path} 不合法或 status 仍是 draft，"
            "已停止，未进入功能代码。补齐后继续。",
            file=sys.stderr,
        )
        return 2
    print(f"[框架] 完成：{context.framework_plan_path}", file=sys.stderr)
    return 0


def _mcp_lines(context: PromptContext) -> list[str]:
    if not context.unity_mcp_server:
        return []
    return [
        f"Unity MCP（服务 {context.unity_mcp_server}）可用：用它确认工程现状；"
        "骨架落地后刷新编译、读控制台确认没有编译错误。连不上就如实说明，不要假装验证过。",
    ]


def _protected_line(paths: list[str]) -> str:
    if not paths:
        return "没有 protectedPaths。"
    return f"不要修改这些路径：{'、'.join(paths)}"
