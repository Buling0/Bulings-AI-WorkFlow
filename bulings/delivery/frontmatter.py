from __future__ import annotations

from typing import Any

import yaml

from bulings.delivery.errors import DeliveryError


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise DeliveryError(code="INVALID_FRONTMATTER", message="缺少 YAML 前置")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise DeliveryError(code="INVALID_FRONTMATTER", message="YAML 前置未闭合")
    raw_yaml = text[4:end]
    body = text[end + 5 :]
    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as error:
        raise DeliveryError(code="INVALID_FRONTMATTER", message="YAML 前置损坏") from error
    if not isinstance(data, dict):
        raise DeliveryError(code="INVALID_FRONTMATTER", message="YAML 前置必须是对象")
    return data, body


def render_frontmatter(meta: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, default_flow_style=False).rstrip()
    if not body.startswith("\n"):
        body = "\n" + body
    return f"---\n{yaml_text}\n---{body}"
