from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.delivery.errors import DeliveryError
from bulings.delivery.lease_flow import check_task_package, prepare_task_package, read_lease, start_slice
from bulings.delivery.review_flow import checkpoint_slice, submit_slice
from tests.test_delivery_slice_plan import _bootstrap_plan_ready, _write_plan_and_slices


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _git_init(project: Path) -> None:
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project, check=True)
    (project / ".gitignore").write_text(".bulings/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)


def _unity_git(project: Path) -> None:
    (project / "Assets").mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings").mkdir()
    _git_init(project)


def _ready_slice(project: Path, archive: Path) -> str:
    plan = """
- 结果：A
  切片：solo
  场景：玩家靠近建筑
  理由：x
"""
    slices = [{"id": "solo", "title": "S", "dependsOn": [], "replaces": []}]
    _write_plan_and_slices(archive, project, "feat", plan, slices)
    from bulings.delivery.slice_plan import approve_slice_plan, check_slice_plan

    digest = check_slice_plan(project, "feat").digest
    approve_slice_plan(project, "feat", digest, now=_fixed_now("2026-10-27T12:00:00+00:00"))
    prepare_task_package(project, "feat", "solo")
    pkg = archive / "05-implementation/packages/solo.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["writeScope"] = ["Assets/Scripts/Reward/RewardView.cs"]
    data["acceptance"] = ["看到奖励"]
    data["validation"] = ["run tests"]
    pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    script = project / "Assets/Scripts/Reward"
    script.mkdir(parents=True, exist_ok=True)
    (script / "RewardView.cs").write_text("// base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "slice files"], cwd=project, check=True, capture_output=True)
    return "solo"


def test_start_slice_and_duplicate_unchanged() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-lease-") as directory:
        project = Path(directory)
        _unity_git(project)
        archive = _bootstrap_plan_ready(project)
        slice_id = _ready_slice(project, archive)
        status_before = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True)
        start_slice(project, "feat", slice_id, "impl-1", now=_fixed_now("2026-10-27T13:00:00+00:00"))
        lease = read_lease(project, "feat")
        assert lease is not None
        rel = "Assets/Scripts/Reward/RewardView.cs"
        assert lease["baseline"]["files"][rel]["existed"] is True
        again = start_slice(project, "feat", slice_id, "impl-1", now=_fixed_now("2026-10-27T14:00:00+00:00"))
        assert again == "unchanged"
        assert lease["startedAt"] == read_lease(project, "feat")["startedAt"]
        status_after = subprocess.run(["git", "status", "--porcelain"], cwd=project, capture_output=True, text=True)
        assert status_before.stdout == status_after.stdout


def test_protected_path_rejected() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-lease-") as directory:
        project = Path(directory)
        _unity_git(project)
        (project / ".bulings").mkdir(exist_ok=True)
        (project / ".bulings/workflow.yaml").write_text("project:\n  protectedPaths:\n    - Assets/Protected\n", encoding="utf-8")
        archive = _bootstrap_plan_ready(project)
        slice_id = _ready_slice(project, archive)
        pkg = archive / "05-implementation/packages/solo.json"
        data = json.loads(pkg.read_text(encoding="utf-8"))
        data["writeScope"] = ["Assets/Protected/Secret.cs"]
        pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        with pytest.raises(DeliveryError):
            start_slice(project, "feat", slice_id, "impl-1", now=_fixed_now("2026-10-27T13:00:00+00:00"))


def test_no_git_no_lease() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-lease-") as directory:
        project = Path(directory)
        (project / "Assets").mkdir()
        (project / "ProjectSettings").mkdir()
        archive = _bootstrap_plan_ready(project)
        plan = """
- 结果：A
  切片：solo
  场景：玩家靠近建筑
  理由：x
"""
        _write_plan_and_slices(archive, project, "feat", plan, [{"id": "solo", "title": "S", "dependsOn": [], "replaces": []}])
        from bulings.delivery.slice_plan import approve_slice_plan, check_slice_plan

        digest = check_slice_plan(project, "feat").digest
        approve_slice_plan(project, "feat", digest, now=_fixed_now("2026-10-27T12:00:00+00:00"))
        prepare_task_package(project, "feat", "solo")
        with pytest.raises(DeliveryError) as error:
            start_slice(project, "feat", "solo", "impl-1", now=_fixed_now("2026-10-27T13:00:00+00:00"))
        assert error.value.code == "GIT_REQUIRED"
        assert read_lease(project, "feat") is None
