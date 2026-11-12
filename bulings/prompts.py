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
    mode: str = "work"
    game: str = ""
    framework_enabled: bool = False
    framework_plan_path: str = ""
    framework_doc_path: str = ""
    framework_summary: str = ""
    framework_hooks: str = ""
    framework_paradigm: str = ""
    project_root: str = ""


@dataclass
class SplitContext:
    feature: str
    design_path: str
    output_path: str
    constraints: str
    protected_paths: list[str]


def format_project_constraints(project: ProjectProfile, knowledge_map: str = "", skill_name: str = "work-feature") -> str:
    lines: list[str] = []
    if knowledge_map:
        lines.append(f"知识库地图：{knowledge_map}（分析前先读，按 {skill_name} 的「知识库」一节使用）")
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


@dataclass
class GddContext:
    """一轮策划案迭代需要的全部输入。"""

    slug: str
    title: str
    brief_path: str
    plan_path: str
    doc_path: str
    round_no: int
    stage: str
    stage_title: str
    options_count: int
    target_rounds: int
    summary: str
    decisions: list[str]
    note: str
    first_round: bool
    constraints: str
    protected_paths: list[str]


def gdd_round_prompt(context: GddContext) -> str:
    dev_spec = ".cursor/skills/indie-design"
    lines = [
        f"先阅读 {dev_spec}/SKILL.md，只做「一轮迭代」；需要时再看 {dev_spec}/dimensions.md 和 {dev_spec}/design-template.md。",
        f"这是第 {context.round_no} 轮，本轮推进「{context.stage_title}」（阶段标识 {context.stage}）。",
        "只写策划案和设计状态，不要写代码，不要建 tasks.json，不要开始做功能。",
        "",
        f"策划案名：{context.title}",
        f"玩法灵感：{context.brief_path}（原文，不要改写它的本意）",
        f"策划案文档（必须更新）：{context.doc_path}",
        f"设计状态（必须更新）：{context.plan_path}",
        "每轮建议轮次：" + f"{context.target_rounds} 轮（玩法 → 剧情 → 风格 → 流程 → 收尾），已经超过就提示开发者可以收尾。",
    ]
    if context.first_round:
        lines += [
            "",
            "这是第一轮：先把灵感读成一份能看见核心乐趣的雏形——核心循环、玩家在做什么、为什么好玩，"
            "写进策划案的概览和玩法部分，然后给出本轮的「玩法」选项。",
        ]
    else:
        lines += ["", f"当前设计状态：", context.summary]
        if context.decisions:
            lines += ["", "开发者在上一轮做的选择（要落实进正文，并写进 chosen）：", *context.decisions]
        else:
            lines += ["", "开发者本轮没有选选项，只给了补充说明，按说明调整。"]
        if context.note:
            lines += ["", f"开发者的补充说明：{context.note}"]
    lines += [
        "",
        "本轮要求：",
        f"1. 针对「{context.stage_title}」给出 {context.options_count} 个开发者选项。选项要真正互斥、"
        "能改变游戏长什么样，每个都写清代价；不要给「都要」「看情况」这类假选项。",
        "2. 选项 id 用阶段字母加序号（例如玩法 G1/G2、剧情 S1/S2、风格 A1/A2、流程 F1/F2），"
        "本轮内唯一，避免和上一轮重名。",
        "3. 把已经确认的内容写进策划案对应章节，不要退化成选项清单；上一轮没定的地方保持「待定」并说明为什么。",
        "4. 更新设计状态：round 写 " + str(context.round_no) + "；stage 写本轮推进的阶段；"
        "status 写 iterating；options 填本轮选项；chosen 追加本轮的选择。"
        "dimensions 里 gameplay/story/style/flow 四项都要在，写 summary 和 confirmed。",
        "5. 不要在策划案里写实现细节（类名、目录、技术方案），那些留给框架阶段。",
        "",
        "项目约束（策划要落在工程做得到的范围内）：",
        context.constraints,
        "",
        _protected_line(context.protected_paths),
        "不要创建 git commit。不要修改 .meta 的 guid。不要动已有代码。",
    ]
    return "\n".join(line for line in lines if line != "")


def gdd_finalize_prompt(context: GddContext) -> str:
    skill = ".cursor/skills/indie-design"
    lines = [
        f"先阅读 {skill}/SKILL.md，只做「定稿」；策划案骨架按 {skill}/design-template.md。",
        "这一轮不再给选项：把策划案补齐成可以直接交给开发的一版，然后收尾。",
        "不要写代码，不要建 tasks.json，不要开始做功能。",
        "",
        f"这是第 {context.round_no} 轮（定稿轮）。",
        f"策划案名：{context.title}",
        f"玩法灵感：{context.brief_path}",
        f"策划案文档（必须补齐）：{context.doc_path}",
        f"设计状态（必须更新）：{context.plan_path}",
        "",
        "当前设计状态：",
        context.summary,
    ]
    if context.decisions:
        lines += ["", "开发者在最后一轮做的选择（要落实进正文，并写进 chosen）：", *context.decisions]
    if context.note:
        lines += ["", f"开发者的补充说明：{context.note}"]
    lines += [
        "",
        "定稿要求：",
        "1. 按骨架补齐：一页概览、核心循环、玩法系统、剧情与世界观、美术风格与音频、游戏流程与关卡节奏、"
        "数值与内容规模、范围与里程碑、还没定的地方。",
        "2. 状态写 round " + str(context.round_no) + "、stage 写 done、status 写 done、options 清空；"
        "chosen 追加本轮的选择（有的话）。",
        "3. 四个维度的 dimensions 都要写 summary 并标 confirmed；确实没法定下来的，在策划案的「还没定的地方」里写明缺什么、"
        "以及什么时候必须定，不要用空话占位。",
        "4. 「范围与里程碑」要按功能粒度给，能直接对上下一步的功能开发。",
        "",
        "项目约束：",
        context.constraints,
        "",
        _protected_line(context.protected_paths),
        "不要创建 git commit。不要修改 .meta 的 guid。不要动已有代码。",
    ]
    return "\n".join(line for line in lines if line != "")


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
