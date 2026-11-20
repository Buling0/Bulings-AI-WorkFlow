"""从玩法灵感迭代策划案：Agent 写 ``design.json``，这里只做确定性的解析和轮次校验。

位置和 ``tasks.py`` / ``framework.py`` 一致：Agent 负责语义（写选项、写正文），
Python 负责"这一轮到底有没有推进""开发者选的那个选项存不存在"。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

GddStage = Literal["core", "story", "style", "flow", "polish", "done"]
GddStatus = Literal["iterating", "done"]
DIMENSIONS = ("gameplay", "story", "style", "flow")
STAGES = ("core", "story", "style", "flow", "polish", "done")
STATUSES = ("iterating", "done")
DIMENSION_TITLES = {
    "gameplay": "玩法",
    "story": "剧情",
    "style": "风格",
    "flow": "流程",
}
STAGE_TITLES = {
    "core": "玩法核心循环",
    "story": "剧情与世界观",
    "style": "美术风格与音频",
    "flow": "游戏流程与关卡节奏",
    "polish": "数值、范围与里程碑",
    "done": "定稿",
}
MIN_ROUND_OPTIONS = 2
_DECISION_SPLIT = re.compile(r"[,，、;；\s]+")


@dataclass
class GddOption:
    id: str
    dimension: str
    label: str
    detail: str = ""
    tradeoff: str = ""


@dataclass
class GddDimension:
    summary: str = ""
    confirmed: bool = False


@dataclass
class GddDecision:
    round: int
    ids: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class GddPlan:
    slug: str
    title: str
    round: int
    stage: GddStage
    status: GddStatus
    dimensions: dict[str, GddDimension]
    options: list[GddOption] = field(default_factory=list)
    chosen: list[GddDecision] = field(default_factory=list)


def parse_gdd_plan(data: object) -> GddPlan | None:
    root = _as_object(data)
    if root is None:
        return None
    if not _non_empty(root.get("slug")) or not _non_empty(root.get("title")):
        return None
    round_no = root.get("round")
    if not _is_positive_int(round_no):
        return None
    stage = root.get("stage")
    if not isinstance(stage, str) or stage not in STAGES:
        return None
    status = root.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        return None

    dimensions = _parse_dimensions(root.get("dimensions"))
    if dimensions is None:
        return None
    options = _parse_options(root.get("options"))
    if options is None:
        return None
    chosen = _parse_chosen(root.get("chosen"))
    if chosen is None:
        return None

    return GddPlan(
        slug=root["slug"],
        title=root["title"],
        round=round_no,
        stage=stage,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        dimensions=dimensions,
        options=options,
        chosen=chosen,
    )


def read_gdd_plan(file_path: str | Path) -> GddPlan | None:
    try:
        text = Path(file_path).read_text(encoding="utf-8")
        return parse_gdd_plan(json.loads(text))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None


def option_ids(plan: GddPlan) -> set[str]:
    return {option.id for option in plan.options}


def find_options(plan: GddPlan, wanted: list[str]) -> tuple[list[GddOption], list[str]]:
    """把开发者写的选项 id 对上当前选项，返回 (找到的, 找不到的)。"""
    by_id = {option.id: option for option in plan.options}
    found: list[GddOption] = []
    missing: list[str] = []
    for item in wanted:
        option = by_id.get(item)
        if option is None:
            missing.append(item)
        else:
            found.append(option)
    return found, missing


def parse_decisions(raw: str) -> list[str]:
    """把 ``"G1,S2  风格3"`` 这样的输入拆成 id 列表，保留顺序并去重。"""
    seen: set[str] = set()
    ids: list[str] = []
    for item in _DECISION_SPLIT.split(raw.strip()):
        token = item.strip()
        if not token or token in seen:
            continue
        seen.add(token)
        ids.append(token)
    return ids


def decided_ids(plan: GddPlan) -> list[str]:
    """这份 plan 里已经做出的选择，按轮次摊平。"""
    ids: list[str] = []
    for decision in plan.chosen:
        ids.extend(decision.ids)
    return ids


def validate_round(
    previous: GddPlan | None,
    current: GddPlan,
    decided: list[str],
    min_options: int = MIN_ROUND_OPTIONS,
    note_given: bool = False,
) -> list[str]:
    """这一轮有没有真的推进。返回空列表表示通过。"""
    errors: list[str] = []
    if previous is None:
        if current.round != 1:
            errors.append(f"第一轮 round 必须是 1，现在是 {current.round}")
        if decided:
            errors.append("第一轮还没有选项可选，--decide 不该出现在这里")
    else:
        expected = previous.round + 1
        if current.round != expected:
            errors.append(f"这一轮应该写 round {expected}，现在是 {current.round}（每一轮只能推进一格）")

    entry = next((item for item in current.chosen if item.round == current.round), None)
    if (decided or note_given) and entry is None:
        errors.append(f"这一轮的选择没有记进 chosen：缺少 round {current.round} 的记录")
    if decided:
        recorded = {item for decision in current.chosen if decision.round == current.round for item in decision.ids}
        missing = [item for item in decided if item not in recorded]
        if missing:
            errors.append("开发者选的选项没有写进 chosen：" + "、".join(missing))

    if current.status == "iterating":
        if len(current.options) < min_options:
            errors.append(
                f"迭代中的一轮至少要给 {min_options} 个选项，现在只有 {len(current.options)} 个"
                "（只能给一个方向时，说明这已经是定稿，用 --finish）"
            )
    elif current.options:
        errors.append("status 是 done 时不该再给新选项，options 需要清空")
    return errors


def finish_dimension_errors(plan: GddPlan) -> list[str]:
    """定稿轮要求四个维度都确认过。返回空列表表示可以定稿。"""
    pending = pending_dimensions(plan)
    if not pending:
        return []
    names = "、".join(dimension_title(name) for name in pending)
    return [f"定稿前四个维度都要确认，还没确认：{names}（确实要放行加 --force）"]


def is_finished(plan: GddPlan | None) -> bool:
    """策划案是不是已经定稿（四个维度都确认）。"""
    return plan is not None and plan.status == "done" and not pending_dimensions(plan)


def design_round_snapshot_path(project_root: str | Path, slug: str, round_no: int) -> Path:
    """每轮 design.json 的快照位置，用于回看决策历史。"""
    return design_dir(project_root, slug) / "rounds" / f"{round_no}.json"


def write_design_snapshot(project_root: str | Path, slug: str, round_no: int, content: str) -> Path | None:
    """把这一轮的 design.json 原文留一份。写不了就不留，不影响主流程。"""
    path = design_round_snapshot_path(project_root, slug, round_no)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    except OSError:
        return None
    return path


def stage_title(stage: str) -> str:
    return STAGE_TITLES.get(stage, stage)


def design_dir(project_root: str | Path, slug: str) -> Path:
    return Path(project_root) / ".bulings" / "design" / slug


def design_plan_path(project_root: str | Path, slug: str) -> Path:
    return design_dir(project_root, slug) / "design.json"


def design_brief_path(project_root: str | Path, slug: str) -> Path:
    return design_dir(project_root, slug) / "brief.md"


def dimension_title(dimension: str) -> str:
    return DIMENSION_TITLES.get(dimension, dimension)


def covered_dimensions(plan: GddPlan) -> list[str]:
    """已经有内容、且确认过的维度。"""
    return [name for name in DIMENSIONS if plan.dimensions[name].confirmed]


def pending_dimensions(plan: GddPlan) -> list[str]:
    return [name for name in DIMENSIONS if not plan.dimensions[name].confirmed]


def plan_summary(plan: GddPlan) -> str:
    """压成几行给提示词和终端用。"""
    lines = [
        f"标题：{plan.title}",
        f"轮次：第 {plan.round} 轮，阶段：{stage_title(plan.stage)}，状态：{plan.status}",
    ]
    for name in DIMENSIONS:
        item = plan.dimensions[name]
        mark = "已确认" if item.confirmed else "待定"
        summary = item.summary.strip() or "（还没写）"
        lines.append(f"- {dimension_title(name)}（{mark}）：{summary}")
    if plan.chosen:
        lines.append("已做的选择：" + "；".join(
            f"第 {decision.round} 轮 {'、'.join(decision.ids) or '仅补充说明'}" for decision in plan.chosen
        ))
    return "\n".join(lines)


def option_lines(plan: GddPlan) -> list[str]:
    """终端里给人看的选项列表。"""
    lines: list[str] = []
    for option in plan.options:
        head = f"  {option.id}  {option.label}"
        lines.append(head)
        if option.detail:
            lines.append(f"        {option.detail}")
        if option.tradeoff:
            lines.append(f"        代价：{option.tradeoff}")
    return lines


def gdd_summary(plan: GddPlan | None) -> str:
    if plan is None:
        return "（第一轮：还没有设计状态，从灵感开始写）"
    return plan_summary(plan)


def plan_status_lines(plan: GddPlan, suggested_rounds: int = 0) -> list[str]:
    """命令行打印的进度与选项。"""
    marks = "、".join(
        f"{dimension_title(name)}{'已确认' if plan.dimensions[name].confirmed else '待定'}" for name in DIMENSIONS
    )
    done = len(covered_dimensions(plan))
    round_part = f"第 {plan.round} 轮" + (f"（建议 {suggested_rounds} 轮）" if suggested_rounds > 0 else "")
    lines = [
        f"进度：{round_part} · 阶段 {stage_title(plan.stage)} · 状态 {plan.status}"
        f"（已确认 {done}/{len(DIMENSIONS)} 个维度）",
        f"维度：{marks}",
    ]
    if plan.options:
        lines.append("本轮选项（用 --decide 选，逗号分隔可多选）：")
        lines.extend(option_lines(plan))
    if suggested_rounds > 0 and plan.round >= suggested_rounds and plan.status != "done":
        lines.append(f"已到建议轮次（{suggested_rounds} 轮），可以考虑 --finish 定稿。")
    if plan.status == "done":
        lines.append("已定稿。要改方向请用 --note 补充，或换一个 --name 重开。")
    return lines


def _parse_dimensions(value: object) -> dict[str, GddDimension] | None:
    root = _as_object(value)
    if root is None:
        return None
    dimensions: dict[str, GddDimension] = {}
    for name in DIMENSIONS:
        item = _as_object(root.get(name))
        if item is None:
            return None
        summary = item.get("summary", "")
        confirmed = item.get("confirmed", False)
        if not isinstance(summary, str) or not isinstance(confirmed, bool):
            return None
        dimensions[name] = GddDimension(summary=summary, confirmed=confirmed)
    return dimensions


def _parse_options(value: object) -> list[GddOption] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    options: list[GddOption] = []
    ids: set[str] = set()
    for item in value:
        root = _as_object(item)
        if root is None:
            return None
        if not _non_empty(root.get("id")) or not _non_empty(root.get("label")):
            return None
        if root["id"] in ids:
            return None
        dimension = root.get("dimension")
        if not isinstance(dimension, str) or dimension not in DIMENSIONS:
            return None
        detail = root.get("detail", "")
        tradeoff = root.get("tradeoff", "")
        if not isinstance(detail, str) or not isinstance(tradeoff, str):
            return None
        ids.add(root["id"])
        options.append(
            GddOption(id=root["id"], dimension=dimension, label=root["label"], detail=detail, tradeoff=tradeoff)
        )
    return options


def _parse_chosen(value: object) -> list[GddDecision] | None:
    if value is None:
        return []
    if not isinstance(value, list):
        return None
    chosen: list[GddDecision] = []
    for item in value:
        root = _as_object(item)
        if root is None:
            return None
        round_no = root.get("round")
        if not _is_positive_int(round_no):
            return None
        ids = root.get("ids", [])
        if not _is_string_array(ids):
            return None
        note = root.get("note", "")
        if not isinstance(note, str):
            return None
        chosen.append(GddDecision(round=round_no, ids=list(ids), note=note))
    return chosen


def _as_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _non_empty(value: object) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _is_string_array(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)
