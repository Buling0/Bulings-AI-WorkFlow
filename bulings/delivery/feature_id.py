from __future__ import annotations

import re

_FEATURE_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


def is_valid_feature_id(value: str) -> bool:
    if not value or len(value) > 64:
        return False
    return _FEATURE_ID_PATTERN.fullmatch(value) is not None
