from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bulings.delivery.errors import DeliveryError


def read_feature_meta(feature_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(feature_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        raise DeliveryError(code="INVALID_FEATURE_JSON", message="无法读取 feature.json") from error
    if not isinstance(data, dict):
        raise DeliveryError(code="INVALID_FEATURE_JSON", message="feature.json 必须是对象")
    return data
