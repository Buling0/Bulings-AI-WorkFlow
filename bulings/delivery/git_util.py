from __future__ import annotations

import subprocess
from pathlib import Path


def is_git_repo(project_root: Path) -> bool:
    return (project_root / ".git").exists()


def git_head(project_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def git_porcelain(project_root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=project_root,
        capture_output=True,
    )
    if result.returncode != 0:
        return {}
    entries: dict[str, str] = {}
    raw = result.stdout.decode("utf-8", errors="replace")
    if not raw:
        return entries
    parts = raw.split("\0")
    index = 0
    while index < len(parts):
        entry = parts[index]
        index += 1
        if not entry or len(entry) < 4:
            continue
        status = entry[:2]
        path = entry[3:]
        if status.startswith("R") and index < len(parts):
            path = parts[index]
            index += 1
        entries[path.replace("\\", "/")] = status
    return entries


def git_hash_file(path: Path) -> str:
    result = subprocess.run(
        ["git", "hash-object", str(path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        from bulings.delivery.fingerprint import content_fingerprint

        return content_fingerprint(path.read_bytes().decode("utf-8", errors="replace")).removeprefix("sha256:")
    return result.stdout.strip()
