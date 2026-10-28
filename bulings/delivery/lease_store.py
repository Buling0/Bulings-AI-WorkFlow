from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bulings.delivery.paths import archive_dir

LEASE_NAME = "lease.json"


def read_lease(project_root: Path, feature_id: str) -> dict[str, Any] | None:
    path = archive_dir(project_root, feature_id) / LEASE_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_lease(project_root: Path, feature_id: str, lease: dict[str, Any]) -> None:
    path = archive_dir(project_root, feature_id) / LEASE_NAME
    path.write_text(json.dumps(lease, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def delete_lease(project_root: Path, feature_id: str) -> None:
    path = archive_dir(project_root, feature_id) / LEASE_NAME
    if path.is_file():
        path.unlink()


def find_global_lease(project_root: Path) -> dict[str, Any] | None:
    root = project_root / ".bulings" / "deliveries"
    if not root.is_dir():
        return None
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        lease_path = entry / LEASE_NAME
        if not lease_path.is_file():
            continue
        data = json.loads(lease_path.read_text(encoding="utf-8"))
        if data.get("status") in {"active", "in_review", "circuit_open"}:
            data = dict(data)
            data["_featureId"] = entry.name
            return data
    return None
