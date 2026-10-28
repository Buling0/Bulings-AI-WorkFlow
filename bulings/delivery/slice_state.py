from __future__ import annotations

import json
from pathlib import Path

from bulings.delivery.archive import archive_dir

STATE_FILE = "05-implementation/slice-state.json"


def _path(project_root: Path, feature_id: str) -> Path:
    return archive_dir(project_root, feature_id) / STATE_FILE


def load_slice_states(project_root: Path, feature_id: str) -> dict[str, dict[str, str]]:
    path = _path(project_root, feature_id)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    slices = data.get("slices")
    if not isinstance(slices, list):
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in slices:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            result[item["id"]] = {
                "state": str(item.get("state", "pending")),
                "candidateId": str(item.get("candidateId", "")),
            }
    return result


def get_slice_state(project_root: Path, feature_id: str, slice_id: str) -> str:
    return load_slice_states(project_root, feature_id).get(slice_id, {}).get("state", "pending")


def set_slice_state(
    project_root: Path,
    feature_id: str,
    slice_id: str,
    state: str,
    *,
    candidate_id: str | None = None,
) -> None:
    path = _path(project_root, feature_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    states = load_slice_states(project_root, feature_id)
    entry = {"state": state}
    if candidate_id:
        entry["candidateId"] = candidate_id
    states[slice_id] = entry
    payload = {"slices": [{"id": sid, **data} for sid, data in sorted(states.items())]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
