"""工作模式的流程图门禁：大功能先出页面交互与数据流图，用户确认后再写代码。

约定很简单：分析阶段把图写到 ``.bulings/runs/<slug>/flow.md``，最后一行是
``<!-- flow-status: draft -->``；用户确认时改成 ``confirmed``（由 ``resume
--confirm-flow`` 写，不靠手改）。这里只负责模板、状态标记和「够不够格放行」。
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_FLOW_PATH = ".bulings/runs/{feature}/flow.md"
DRAFT_MARKER = "<!-- flow-status: draft -->"
CONFIRMED_PREFIX = "<!-- flow-status: confirmed"
# 流程图至少要有这些内容才算写出来了，避免空壳过门禁。
_MIN_CHARS = 200


def flow_file_path(project_root: str | os.PathLike[str], slug: str) -> Path:
    return Path(project_root) / ".bulings" / "runs" / slug / "flow.md"


def flow_template(feature: str, design_path: str, created_at: str = "") -> str:
    stamp = f"    生成时间：{created_at}" if created_at else ""
    return "\n".join(
        [
            f"# {feature} 页面交互与数据流",
            "",
            f"> 功能名：{feature}    策划案：{design_path}{stamp}",
            "> 这是写代码前的确认稿：看完没问题再 `bulings resume --confirm-flow`。",
            "",
            "## 页面与入口",
            "",
            "- 页面/界面清单，以及从哪个入口打开：",
            "",
            "## 页面交互流程",
            "",
            "```mermaid",
            "flowchart TD",
            "  A[入口] --> B[页面]",
            "```",
            "",
            "## 数据流向",
            "",
            "- 数据从哪来（服务端 / 配置 / 本地状态）：",
            "- 经过哪些脚本或模块：",
            "- 落到哪里、谁负责刷新界面：",
            "",
            "## 待确认",
            "",
            "- 有疑问的地方列在这里，没有就写「无」。",
            "",
            DRAFT_MARKER,
            "",
        ]
    )


def is_confirmed(text: str) -> bool:
    return any(line.strip().startswith(CONFIRMED_PREFIX) for line in text.splitlines())


def confirm_flow_markdown(text: str, confirmed_at: str) -> str:
    """把 draft 标记替换成确认标记；没标记就补在末尾。"""
    lines = [line for line in text.splitlines() if not line.strip().startswith("<!-- flow-status:")]
    while lines and not lines[-1].strip():
        lines.pop()
    lines.append("")
    lines.append(f"{CONFIRMED_PREFIX} by user at {confirmed_at} -->")
    return "\n".join(lines) + "\n"


def confirm_flow_file(path: Path, confirmed_at: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    path.write_text(confirm_flow_markdown(text, confirmed_at), encoding="utf-8", newline="\n")
    return True


def flow_problems(path: Path) -> list[str]:
    """流程图有没有写到能放行的程度。返回空列表表示可以确认。"""
    if not path.is_file():
        return [f"流程图还没有写出来：{path}"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return [f"读不了流程图 {path}：{error}"]
    problems: list[str] = []
    if "```mermaid" not in text:
        problems.append("流程图里没有 mermaid 图")
    if "## 页面" not in text and "## 页面与入口" not in text:
        problems.append("流程图里没有「页面与入口」一节")
    if "## 数据流向" not in text:
        problems.append("流程图里没有「数据流向」一节")
    if len(text.strip()) < _MIN_CHARS:
        problems.append("流程图内容太少，像是空壳")
    return problems


def flow_ready_for_gate(path: Path) -> bool:
    return path.is_file() and is_confirmed(path.read_text(encoding="utf-8", errors="replace"))


def describe_flow_gate(feature: str, slug: str, path: Path) -> str:
    """停住时给用户看的那几行。"""
    return "\n".join(
        [
            f"[流程图] 已生成：{path}",
            "请看完页面交互和数据流。确认后执行：",
            f'  bulings resume --project "<Unity工程>" --run {slug} --confirm-flow',
            "想跳过这张图（这个功能不需要确认）：加 --no-flow 再 resume。",
        ]
    )
