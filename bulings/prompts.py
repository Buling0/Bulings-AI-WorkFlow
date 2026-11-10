from __future__ import annotations

from dataclasses import dataclass

from bulings.config import ProjectProfile
from bulings.tasks import FeatureTask


@dataclass
class PromptContext:
    feature: str
    slug: str
    design_path: str
    prefab_paths: list[str]
    tasks_path: str
    dev_spec_enabled: bool
    feature_doc_enabled: bool
    dev_spec_path: str
    feature_doc_path: str
    constraints: str
    protected_paths: list[str]
    unity_mcp_server: str = ""
    client_spec_path: str = ""
    knowledge_root: str = ""
    knowledge_map: str = ""


@dataclass
class SplitContext:
    feature: str
    design_path: str
    output_path: str
    constraints: str
    protected_paths: list[str]


def format_project_constraints(project: ProjectProfile, knowledge_map: str = "") -> str:
    lines: list[str] = []
    if knowledge_map:
        lines.append(f"知识库地图：{knowledge_map}（分析前先读，按 work-feature 的「知识库」一节使用）")
    if project.code_roots:
        lines.append(f"代码目录：{'、'.join(project.code_roots)}")
    if project.namespaces:
        lines.append(f"命名空间：{'、'.join(project.namespaces)}")
    if project.asmdefs:
        lines.append(f"程序集：{'、'.join(project.asmdefs)}")
    if project.ui.framework:
        lines.append(f"UI 框架：{project.ui.framework}")
    if project.ui.binding:
        lines.append(f"UI 绑定：{project.ui.binding}")
    if project.ui.notes:
        lines.append(f"UI 说明：{project.ui.notes}")
    if project.architecture:
        lines.append(f"架构：{project.architecture}")
    if project.style:
        lines.append(f"代码风格：{project.style}")
    if not lines:
        return (
            "项目适配项都未配置。从工程推断目录、命名空间和程序集，写入开发说明的「推断的项目约定」。"
            "不要把未配置项写成硬性规范。"
        )
    return "\n".join(lines)


def analyze_prompt(context: PromptContext) -> str:
    prefabs = "\n".join(f"- {item}" for item in context.prefab_paths)
    if context.dev_spec_enabled:
        dev_spec = f"开发说明：写入 {context.dev_spec_path}，按 .cursor/skills/work-feature/dev-spec-template.md。"
    else:
        dev_spec = "开发说明：不要生成。"
    return "\n".join(
        [
            "先阅读 .cursor/skills/work-feature/SKILL.md，并只执行其中的「分析」阶段。",
            "不要写玩法代码，不要实现任务，不要写功能说明。",
            "",
            f"功能名：{context.feature}",
            f"策划案：{context.design_path}",
            "预制体：",
            prefabs,
            f"任务文件（必须写入）：{context.tasks_path}",
            dev_spec,
            "",
            "项目约束：",
            context.constraints,
            "",
            _protected_line(context.protected_paths),
            "不要创建 git commit。不要修改 .meta 的 guid。不要启动 Unity 批处理编译。",
            *_mcp_lines(context, "analyze"),
            "tasks.json 的 status 只能是 pending、in_progress、done、blocked。至少一项任务。id 不要重复。",
            "策划和预制体不一致时，该项 status 为 blocked，并写 blockedReason。",
        ]
    )


def implement_prompt(context: PromptContext, task: FeatureTask, retry: bool) -> str:
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
    lines = [
        "先阅读 .cursor/skills/work-feature/SKILL.md，并只执行其中的「实现一个任务」。",
        f"本轮只实现任务 {task.id}：{task.title}。不要开始下一个任务，不要写功能说明。",
        retry_line,
        reason,
        f"目标：{task.goal}",
        f"完成标准：{acceptance}",
        f"任务文件：{context.tasks_path}",
        dev_spec,
        _protected_line(context.protected_paths),
        "做完把该任务标成 done。无法在不脑补的前提下完成时标成 blocked，并写 blockedReason。",
        "不要创建 git commit。不要修改 .meta 的 guid。",
    ]
    return "\n".join(line for line in lines if line != "")


def document_prompt(context: PromptContext) -> str:
    return "\n".join(
        [
            "先阅读 .cursor/skills/work-feature/SKILL.md，并只执行其中的「功能说明」。",
            "不要再改玩法代码。不要把任务清单再抄一遍。",
            f"功能名：{context.feature}",
            f"策划案：{context.design_path}",
            f"任务文件：{context.tasks_path}",
            f"功能说明写入：{context.feature_doc_path}",
            "按 .cursor/skills/work-feature/feature-doc-template.md，依据实际改过的代码来写。",
            "写清：功能做什么、入口、主要类型、数据流、依赖的项目模块、修改时要动哪些文件、已知限制、和策划不一致的地方。",
            *_knowledge_update_lines(context),
        ]
    )


def split_prompt(context: SplitContext) -> str:
    return "\n".join(
        [
            "先阅读 .cursor/skills/client-split/SKILL.md，并按它把策划案里客户端要开发的内容分离出来。",
            "只读策划案和工程，只写客户端开发需求文档，不要写玩法代码，不要建 tasks.json。",
            "",
            f"功能名：{context.feature}",
            f"策划案：{context.design_path}",
            f"客户端需求文档（必须写入）：{context.output_path}",
            "",
            "项目约束：",
            context.constraints,
            "",
            _protected_line(context.protected_paths),
            "不要创建 git commit。不要修改 .meta 的 guid。",
            "归属不明的条目放进文档的「待确认」，不要自行归入客户端。",
        ]
    )


def _knowledge_update_lines(context: PromptContext) -> list[str]:
    if not context.knowledge_map:
        return []
    return [
        f"知识库已存在（地图 {context.knowledge_map}）。功能说明写完后，按 .cursor/skills/knowledge-base/SKILL.md 的 update 动作，"
        "只更新受本功能影响的知识库页面；无需更新就明说，不要为了有产出而改。",
    ]


@dataclass
class KnowledgeContext:
    action: str
    root: str
    feature: str
    tasks_path: str
    constraints: str
    protected_paths: list[str]


def knowledge_prompt(context: KnowledgeContext) -> str:
    lines = [
        f"先阅读 .cursor/skills/knowledge-base/SKILL.md，并只执行其中的 {context.action} 动作。不要写玩法代码。",
        f"知识库根目录：{context.root}",
    ]
    if context.action == "update":
        lines.append(f"功能名：{context.feature}；任务文件：{context.tasks_path}（据此和 git 工作区改动确定受影响的模块）。")
    if context.action == "check":
        lines.append(f"只读核对，报告写到 {context.root}/CHECK.md，不要改其他知识库页面。")
    lines += [
        "",
        "项目约束：",
        context.constraints,
        "",
        _protected_line(context.protected_paths),
        "不要创建 git commit。不要修改 .meta 的 guid。读不到证据的写进「待核实」，不要脑补。",
    ]
    return "\n".join(lines)


def _mcp_lines(context: PromptContext, phase: str) -> list[str]:
    if not context.unity_mcp_server:
        return []
    server = context.unity_mcp_server
    if phase == "analyze":
        return [f"Unity MCP（服务 {server}）可用：只用来读场景、预制体层级和控制台，分析阶段不要修改场景或资源。"]
    return [
        f"Unity MCP（服务 {server}）可用。按 .cursor/skills/work-feature/unity-mcp.md 使用："
        "改完脚本后用它刷新、读控制台确认无编译错误，需要时在编辑器里绑定预制体引用。",
        "MCP 连不上时如实写进该项的 blockedReason 或说明，不要假装已验证。",
    ]


def _protected_line(paths: list[str]) -> str:
    if not paths:
        return "没有 protectedPaths。"
    return f"不要修改这些路径：{'、'.join(paths)}"
