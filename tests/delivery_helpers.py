from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from bulings.delivery.lease_flow import prepare_task_package, start_slice
from bulings.delivery.review_flow import checkpoint_slice, review_slice, submit_slice
from bulings.delivery.slice_plan import approve_slice_plan, check_slice_plan
from tests.test_delivery_slice_plan import _bootstrap_plan_ready, _write_plan_and_slices


def fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def git_init(project: Path) -> None:
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=project, check=True)
    (project / ".gitignore").write_text(".bulings/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)


def unity_git(project: Path) -> None:
    (project / "Assets").mkdir(parents=True, exist_ok=True)
    (project / "ProjectSettings").mkdir()
    git_init(project)


def ready_slice(
    project: Path,
    archive: Path,
    *,
    slice_id: str = "solo",
    script_rel: str = "Assets/Scripts/Reward/RewardView.cs",
    validation: list[str] | None = None,
) -> str:
    plan = f"""
- 结果：A
  切片：{slice_id}
  场景：玩家靠近建筑
  理由：x
"""
    slices = [{"id": slice_id, "title": "S", "dependsOn": [], "replaces": []}]
    _write_plan_and_slices(archive, project, "feat", plan, slices)
    digest = check_slice_plan(project, "feat").digest
    approve_slice_plan(project, "feat", digest, now=fixed_now("2026-10-27T12:00:00+00:00"))
    prepare_task_package(project, "feat", slice_id)
    pkg = archive / "05-implementation/packages" / f"{slice_id}.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["writeScope"] = [script_rel]
    data["acceptance"] = ["看到奖励"]
    data["validation"] = validation or ["run tests"]
    pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    script = project / script_rel
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("// base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "slice files"], cwd=project, check=True, capture_output=True)
    return slice_id


def activate_slice(
    project: Path,
    archive: Path,
    slice_id: str,
    *,
    edit_rel: str,
    execution_id: str = "impl-1",
    validation: list[str] | None = None,
) -> None:
    """在方案与任务包已就绪时启动切片并完成检查点（不再改写方案）。"""
    pkg = archive / "05-implementation/packages" / f"{slice_id}.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    data["writeScope"] = [edit_rel]
    data["acceptance"] = data.get("acceptance") or ["看到奖励"]
    data["validation"] = validation or data.get("validation") or ["run tests"]
    pkg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    script = project / edit_rel
    script.parent.mkdir(parents=True, exist_ok=True)
    if not script.is_file():
        script.write_text("// base\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "slice files"], cwd=project, check=True, capture_output=True)
    start_slice(project, "feat", slice_id, execution_id, now=fixed_now("2026-10-27T13:00:00+00:00"))
    script.write_text(script.read_text(encoding="utf-8") + "// change\n", encoding="utf-8")
    covered = validation or data["validation"]
    checkpoint_slice(
        project,
        "feat",
        execution_id,
        "done",
        "passed",
        covered_validation=covered,
        now=fixed_now("2026-10-27T13:30:00+00:00"),
    )


def start_and_implement(
    project: Path,
    archive: Path,
    slice_id: str,
    *,
    execution_id: str = "impl-1",
    edit_rel: str = "Assets/Scripts/Reward/RewardView.cs",
    validation: list[str] | None = None,
) -> None:
    ready_slice(
        project,
        archive,
        slice_id=slice_id,
        script_rel=edit_rel,
        validation=validation,
    )
    start_slice(project, "feat", slice_id, execution_id, now=fixed_now("2026-10-27T13:00:00+00:00"))
    path = project / edit_rel
    path.write_text(path.read_text(encoding="utf-8") + "// change\n", encoding="utf-8")
    covered = validation or ["run tests"]
    checkpoint_slice(
        project,
        "feat",
        execution_id,
        "done",
        "passed",
        covered_validation=covered,
        now=fixed_now("2026-10-27T13:30:00+00:00"),
    )


def submit_and_pass(
    project: Path,
    execution_id: str = "impl-1",
    reviewer: str = "review-1",
) -> str:
    candidate_id = submit_slice(project, "feat", execution_id, now=fixed_now("2026-10-27T14:00:00+00:00"))
    review_slice(
        project,
        "feat",
        candidate_id,
        reviewer,
        "pass",
        "ok",
        now=fixed_now("2026-10-27T14:30:00+00:00"),
    )
    return candidate_id


def bootstrap_plan(project: Path) -> Path:
    unity_git(project)
    return _bootstrap_plan_ready(project)
