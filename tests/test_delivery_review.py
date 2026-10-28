from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bulings.delivery.errors import DeliveryError
from bulings.delivery.lease_store import read_lease
from bulings.delivery.review_flow import submit_slice
from bulings.delivery.archive import delivery_status
from bulings.delivery.slice_plan import check_slice_plan
from bulings.delivery.lease_flow import start_slice
from bulings.delivery.review_flow import review_slice, submit_slice as submit
from bulings.delivery.lease_flow import prepare_task_package
from tests.delivery_helpers import (
    activate_slice,
    bootstrap_plan,
    fixed_now,
    ready_slice,
    start_and_implement,
    submit_and_pass,
)


def test_submit_outside_file_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-review-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        (project / "Assets/Outside.cs").write_text("x", encoding="utf-8")
        with pytest.raises(DeliveryError) as error:
            submit_slice(project, "feat", "impl-1", now=fixed_now("2026-10-27T14:00:00+00:00"))
        assert error.value.code == "WORKSPACE_SCOPE_VIOLATION"
        assert read_lease(project, "feat") is not None


def test_empty_candidate_rejected() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-review-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        ready_slice(project, archive)
        start_slice(project, "feat", "solo", "impl-1", now=fixed_now("2026-10-27T13:00:00+00:00"))
        with pytest.raises(DeliveryError) as error:
            submit_slice(project, "feat", "impl-1", now=fixed_now("2026-10-27T14:00:00+00:00"))
        assert error.value.code == "EMPTY_CANDIDATE"


def test_review_not_independent() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-review-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        cid = submit(project, "feat", "impl-1", now=fixed_now("2026-10-27T14:00:00+00:00"))
        with pytest.raises(DeliveryError) as error:
            review_slice(project, "feat", cid, "impl-1", "pass", "no", now=fixed_now("2026-10-27T15:00:00+00:00"))
        assert error.value.code == "REVIEW_NOT_INDEPENDENT"


def test_pass_unblocks_dependent_slice() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-review-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        from tests.test_delivery_slice_plan import _write_plan_and_slices
        from bulings.delivery.slice_plan import approve_slice_plan

        plan = """
- 结果：A
  切片：first
  场景：玩家靠近建筑
  理由：a
- 结果：B
  切片：second
  场景：玩家靠近建筑
  理由：b
"""
        slices = [
            {"id": "first", "title": "F", "dependsOn": [], "replaces": []},
            {"id": "second", "title": "S", "dependsOn": ["first"], "replaces": []},
        ]
        _write_plan_and_slices(archive, project, "feat", plan, slices)
        digest = check_slice_plan(project, "feat").digest
        approve_slice_plan(project, "feat", digest, now=fixed_now("2026-10-27T12:00:00+00:00"))
        prepare_task_package(project, "feat", "first")
        prepare_task_package(project, "feat", "second")
        activate_slice(project, archive, "first", edit_rel="Assets/Scripts/A.cs")
        submit_and_pass(project)
        status = delivery_status(project, "feat")
        second = next(s for s in status.slices if s["id"] == "second")
        assert second["eligibility"] == "ready"
        assert read_lease(project, "feat") is None
