"""工作模式：沿用 ``prompts.py`` 里的提示词，行为与之前完全一致。"""

from __future__ import annotations

from bulings.modes.base import WORK_SKILL_DIR, ModeStrategy
from bulings.prompts import analyze_prompt, document_prompt, implement_prompt


def work_strategy() -> ModeStrategy:
    return ModeStrategy(
        name="work",
        skill_dir=WORK_SKILL_DIR,
        requires_prefab=True,
        analyze_prompt=analyze_prompt,
        implement_prompt=implement_prompt,
        document_prompt=document_prompt,
    )
