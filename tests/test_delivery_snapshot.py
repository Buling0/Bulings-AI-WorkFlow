from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from bulings.delivery.archive import init_delivery
from bulings.delivery.errors import DeliveryError
from bulings.delivery.snapshot_flow import snapshot_list, snapshot_restore, snapshot_save
from tests.delivery_helpers import bootstrap_plan, fixed_now, unity_git


def test_snapshot_save_unchanged_and_restore() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-snap-") as directory:
        project = Path(directory)
        unity_git(project)
        init_delivery(project, "feat", "t", now=fixed_now("2026-10-27T08:00:00+00:00"))
        head_before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
        first = snapshot_save(
            project,
            "feat",
            "stage-start",
            stage="requirements",
            now=fixed_now("2026-10-27T09:00:00+00:00"),
        )
        second = snapshot_save(
            project,
            "feat",
            "stage-start",
            stage="requirements",
            now=fixed_now("2026-10-27T09:01:00+00:00"),
        )
        assert first["commit"] == second["commit"]
        req = project / ".bulings/deliveries/feat/01-requirements/README.md"
        original = req.read_text(encoding="utf-8")
        req.write_text(original + "\n<!-- edit -->\n", encoding="utf-8")
        third = snapshot_save(
            project,
            "feat",
            "manual",
            name="after-edit",
            now=fixed_now("2026-10-27T09:02:00+00:00"),
        )
        assert third["commit"] != first["commit"]
        assert len(snapshot_list(project, "feat")) >= 2
        preview = snapshot_restore(project, "feat", first["commit"])
        assert preview["status"] == "preview"
        assert req.read_text(encoding="utf-8") != original
        snapshot_restore(project, "feat", first["commit"], execute=True)
        assert "edit" not in req.read_text(encoding="utf-8")
        head_after = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
        assert head_before == head_after


def test_restore_fails_with_lease() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-snap-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        from bulings.delivery.lease_flow import start_slice
        from tests.delivery_helpers import ready_slice

        ready_slice(project, archive)
        snap = snapshot_save(project, "feat", "manual", name="a", now=fixed_now("2026-10-27T10:00:00+00:00"))
        start_slice(project, "feat", "solo", "impl-1", now=fixed_now("2026-10-27T10:01:00+00:00"))
        req = project / ".bulings/deliveries/feat/01-requirements/README.md"
        before = req.read_bytes()
        with pytest.raises(DeliveryError) as error:
            snapshot_restore(project, "feat", snap["commit"], execute=True)
        assert error.value.code == "LEASE_ACTIVE"
        assert req.read_bytes() == before
