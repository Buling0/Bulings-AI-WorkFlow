"""工作模式：沿用 ``prompts.py`` 里的提示词，行为与之前完全一致。"""

from __future__ import annotations

from bulings.modes.base import WORK_SKILL_DIR, ModeStrategy
from bulings.prompts import PromptContext, analyze_prompt, document_prompt, implement_prompt
from bulings.tasks import TaskFile, validate_task_dependencies


def _validate_work_tasks(task_file: TaskFile, context: PromptContext) -> list[str]:
    """工作模式不做切片和框架校验，只查依赖写错没有。"""
    return validate_task_dependencies(task_file.tasks)


def work_strategy() -> ModeStrategy:
    return ModeStrategy(
        name="work",
        skill_dir=WORK_SKILL_DIR,
        requires_prefab=True,
        analyze_prompt=analyze_prompt,
        implement_prompt=implement_prompt,
        document_prompt=document_prompt,
        validate_tasks=_validate_work_tasks,
    )
