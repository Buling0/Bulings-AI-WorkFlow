from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from bulings.delivery.errors import DeliveryError
from bulings.delivery.lease_flow import expand_write_scope, load_task_package
from bulings.delivery.lease_store import read_lease
from bulings.delivery.time_util import format_iso8601


def snapshot_save(
    project_root: Path,
    feature_id: str,
    reason: str,
    *,
    stage: str | None = None,
    name: str | None = None,
    now,
) -> dict[str, str]:
    project_root = project_root.resolve()
    archive = project_root / ".bulings" / "deliveries" / feature_id
    repo = archive / "snapshots.git"
    if not repo.exists():
        subprocess.run(["git", "init", "--bare", str(repo)], check=True, capture_output=True)
    body = {
        "featureId": feature_id,
        "reason": reason,
        "stage": stage,
        "name": name,
        "createdAt": format_iso8601(now()),
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "tree"
        work.mkdir()
        _copy_archive(archive, work / "archive")
        lease = read_lease(project_root, feature_id)
        if lease and lease.get("status") in {"active", "in_review", "circuit_open"}:
            scope_dir = work / "scope"
            scope_dir.mkdir()
            package = load_task_package(project_root, feature_id, str(lease.get("sliceId")))
            for rel in expand_write_scope(project_root, package.get("writeScope", [])):
                src = project_root / rel
                if src.is_file():
                    dest = scope_dir / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
        tree_id = _write_tree(repo, work)
        last = _last_commit_body(repo)
        if (
            last
            and last.get("reason") == reason
            and last.get("stage") == stage
            and last.get("name") == name
            and last.get("featureId") == feature_id
            and _last_tree(repo) == tree_id
        ):
            commit = subprocess.run(
                ["git", "--git-dir", str(repo), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            return {"status": "unchanged", "commit": commit}
        subprocess.run(["git", "--git-dir", str(repo), "--work-tree", str(work), "add", "-A"], check=True, capture_output=True)
        subject = f"{reason} {stage or name or ''}".strip()
        subprocess.run(
            [
                "git",
                "--git-dir",
                str(repo),
                "--work-tree",
                str(work),
                "commit",
                "-m",
                subject,
                "--allow-empty",
                "-m",
                json.dumps(body, ensure_ascii=False),
            ],
            check=True,
            capture_output=True,
        )
        commit = subprocess.run(
            ["git", "--git-dir", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return {"status": "saved", "commit": commit}


def snapshot_list(project_root: Path, feature_id: str) -> list[dict[str, str]]:
    repo = project_root / ".bulings" / "deliveries" / feature_id / "snapshots.git"
    if not repo.exists():
        return []
    result = subprocess.run(
        ["git", "--git-dir", str(repo), "log", "--pretty=format:%H|%s"],
        capture_output=True,
        text=True,
    )
    snapshots: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if "|" not in line:
            continue
        commit, subject = line.split("|", 1)
        body = _commit_body(repo, commit)
        snapshots.append(
            {
                "id": commit,
                "subject": subject,
                "createdAt": str(body.get("createdAt", "")),
                "reason": str(body.get("reason", subject)),
                "stage": str(body.get("stage") or ""),
                "name": str(body.get("name") or ""),
            }
        )
    return snapshots


def snapshot_restore(
    project_root: Path,
    feature_id: str,
    snapshot_id: str,
    *,
    execute: bool = False,
) -> dict[str, object]:
    project_root = project_root.resolve()
    archive = project_root / ".bulings" / "deliveries" / feature_id
    lease = read_lease(project_root, feature_id)
    lease_state = "none" if lease is None else str(lease.get("status", "active"))
    archive_changes, scope_changes = _diff_snapshot(project_root, feature_id, snapshot_id)
    preview = {"status": "preview", "archiveChanges": archive_changes, "scopeChanges": scope_changes, "lease": lease_state}
    if not execute:
        return preview
    if lease is not None:
        raise DeliveryError(code="LEASE_ACTIVE", message="存在租约", exit_code=1)
    meta = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
    if meta.get("lifecycle") == "frozen":
        raise DeliveryError(code="FROZEN", message="已冻结", exit_code=1)
    backup: list[tuple[Path, bytes | None]] = []
    try:
        tree = _checkout_snapshot_tree(project_root, feature_id, snapshot_id)
        for rel in archive_changes:
            target = archive / rel
            backup.append((target, target.read_bytes() if target.is_file() else None))
        for rel in scope_changes:
            target = project_root / rel
            backup.append((target, target.read_bytes() if target.is_file() else None))
        _apply_snapshot_tree(project_root, feature_id, tree)
        save = snapshot_save(project_root, feature_id, "before-overwrite", now=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
        return {"status": "restored", "snapshotId": save.get("commit", snapshot_id)}
    except Exception:
        for path, content in backup:
            if content is None:
                if path.is_file():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        raise


def _copy_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in archive.iterdir():
        if item.name in {"snapshots.git", "baselines"}:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        elif item.is_file():
            shutil.copy2(item, target)


def _write_tree(repo: Path, work: Path) -> str:
    subprocess.run(["git", "--git-dir", str(repo), "--work-tree", str(work), "add", "-A"], check=True, capture_output=True)
    return subprocess.run(
        ["git", "--git-dir", str(repo), "--work-tree", str(work), "write-tree"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _last_tree(repo: Path) -> str | None:
    if subprocess.run(["git", "--git-dir", str(repo), "rev-parse", "HEAD"], capture_output=True).returncode != 0:
        return None
    return subprocess.run(
        ["git", "--git-dir", str(repo), "rev-parse", "HEAD^{tree}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _last_commit_body(repo: Path) -> dict | None:
    if subprocess.run(["git", "--git-dir", str(repo), "rev-parse", "HEAD"], capture_output=True).returncode != 0:
        return None
    commit = subprocess.run(
        ["git", "--git-dir", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return _commit_body(repo, commit)


def _commit_body(repo: Path, commit: str) -> dict:
    msg = subprocess.run(
        ["git", "--git-dir", str(repo), "log", "-1", "--format=%B", commit],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    lines = [line for line in msg.splitlines() if line.strip()]
    if len(lines) >= 2:
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            pass
    return {}


def _checkout_snapshot_tree(project_root: Path, feature_id: str, snapshot_id: str) -> Path:
    repo = project_root / ".bulings" / "deliveries" / feature_id / "snapshots.git"
    tmp = Path(tempfile.mkdtemp(prefix="bulings-snap-"))
    extract = tmp / "extract"
    extract.mkdir()
    archive_bytes = subprocess.run(
        ["git", "--git-dir", str(repo), "archive", snapshot_id],
        capture_output=True,
        check=True,
    ).stdout
    subprocess.run(["tar", "-xf", "-"], input=archive_bytes, cwd=extract, check=True)
    return extract


def _diff_snapshot(project_root: Path, feature_id: str, snapshot_id: str) -> tuple[list[str], list[str]]:
    tree = _checkout_snapshot_tree(project_root, feature_id, snapshot_id)
    tmp_root = tree.parent
    archive = project_root / ".bulings" / "deliveries" / feature_id
    archive_changes: list[str] = []
    snap_archive = tree / "archive"
    if snap_archive.is_dir():
        for path in snap_archive.rglob("*"):
            if path.is_file():
                rel = path.relative_to(snap_archive).as_posix()
                current = archive / rel
                if not current.is_file() or current.read_bytes() != path.read_bytes():
                    archive_changes.append(rel)
    scope_changes: list[str] = []
    snap_scope = tree / "scope"
    if snap_scope.is_dir():
        for path in snap_scope.rglob("*"):
            if path.is_file():
                rel = path.relative_to(snap_scope).as_posix()
                current = project_root / rel
                if not current.is_file() or current.read_bytes() != path.read_bytes():
                    scope_changes.append(rel)
    shutil.rmtree(tmp_root, ignore_errors=True)
    return sorted(archive_changes), sorted(scope_changes)


def _apply_snapshot_tree(project_root: Path, feature_id: str, tree: Path) -> None:
    archive = project_root / ".bulings" / "deliveries" / feature_id
    snap_archive = tree / "archive"
    if snap_archive.is_dir():
        for path in snap_archive.rglob("*"):
            if path.is_file():
                rel = path.relative_to(snap_archive).as_posix()
                target = archive / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
    snap_scope = tree / "scope"
    if snap_scope.is_dir():
        for path in snap_scope.rglob("*"):
            if path.is_file():
                rel = path.relative_to(snap_scope).as_posix()
                target = project_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
