"""模式策略层：把"工作模式"和"独游模式"的差异收在这里。

``runner`` 只有一份驱动循环，模式差异通过 :class:`ModeStrategy` 注入：提示词怎么拼、
要不要预制体、有没有阶段前置钩子（独游模式的框架阶段）、任务做完后还要不要语义校验。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bulings.prompts import PromptContext
from bulings.tasks import FeatureTask, TaskFile

WORK_SKILL_DIR = ".cursor/skills/work-feature"
INDIE_SKILL_DIR = ".cursor/skills/indie-feature"
INDIE_DESIGN_SKILL_DIR = ".cursor/skills/indie-design"
SKILL_DIRS = {"work": WORK_SKILL_DIR, "indie": INDIE_SKILL_DIR}
MODES = ("work", "indie")


@dataclass
class ModeEnv:
    """给阶段前置钩子用的上下文，避免 ``modes`` 反向 import ``runner``。"""

    project_root: str
    context: PromptContext
    save_state: Callable[[], None]
    send: Callable[[str], int]


@dataclass(frozen=True)
class ModeStrategy:
    name: str
    skill_dir: str
    requires_prefab: bool
    analyze_prompt: Callable[[PromptContext], str]
    implement_prompt: Callable[[PromptContext, FeatureTask, bool], str]
    document_prompt: Callable[[PromptContext], str]
    prepare: Callable[[ModeEnv], int] | None = None
    validate_tasks: Callable[[TaskFile, PromptContext], list[str]] | None = None


def skill_dir_for(mode: str) -> str:
    try:
        return SKILL_DIRS[mode]
    except KeyError:
        raise ValueError(f"未知的工作流模式：{mode}") from None


def requires_prefab(mode: str) -> bool:
    return mode != "indie"
