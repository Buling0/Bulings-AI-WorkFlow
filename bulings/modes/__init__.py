"""工作流模式策略。"""

from __future__ import annotations

from bulings.modes.base import (
    INDIE_DESIGN_SKILL_DIR,
    INDIE_SKILL_DIR,
    WORK_SKILL_DIR,
    ModeEnv,
    ModeStrategy,
    requires_prefab,
    skill_dir_for,
)
from bulings.modes.indie import indie_strategy
from bulings.modes.work import work_strategy
from bulings.prompts import PromptContext


def strategy_for(mode: str, context: PromptContext) -> ModeStrategy:
    if mode == "work":
        return work_strategy()
    if mode == "indie":
        return indie_strategy(context)
    raise ValueError(f"未知的工作流模式：{mode}")


__all__ = [
    "INDIE_DESIGN_SKILL_DIR",
    "INDIE_SKILL_DIR",
    "WORK_SKILL_DIR",
    "ModeEnv",
    "ModeStrategy",
    "indie_strategy",
    "requires_prefab",
    "skill_dir_for",
    "strategy_for",
    "work_strategy",
]
