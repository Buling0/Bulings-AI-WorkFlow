from __future__ import annotations

import hashlib


def content_fingerprint(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
