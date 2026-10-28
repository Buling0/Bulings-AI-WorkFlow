from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from bulings.delivery.circuit_flow import interrupt_slice, open_circuit, resolve_slice
from bulings.delivery.errors import DeliveryError
from bulings.delivery.lease_store import read_lease
from bulings.delivery.review_flow import submit_slice
from tests.delivery_helpers import bootstrap_plan, fixed_now, start_and_implement, submit_and_pass


def test_circuit_blocks_submit_then_retry() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-circuit-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        open_circuit(project, "feat", "impl-1", "scope-required", "需要改 meta", now=fixed_now("2026-10-27T13:40:00+00:00"))
        with pytest.raises(DeliveryError) as error:
            submit_slice(project, "feat", "impl-1", now=fixed_now("2026-10-27T14:00:00+00:00"))
        assert error.value.code == "CIRCUIT_OPEN"
        resolve_slice(project, "feat", "retry", execution_id="impl-2")
        assert read_lease(project, "feat")["executionId"] == "impl-2"
        from bulings.delivery.review_flow import checkpoint_slice

        checkpoint_slice(
            project,
            "feat",
            "impl-2",
            "fixed",
            "passed",
            covered_validation=["run tests"],
            now=fixed_now("2026-10-27T13:50:00+00:00"),
        )
        submit_and_pass(project, execution_id="impl-2", reviewer="review-1")


def test_interrupt_restores_scope_file() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-circuit-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        rel = "Assets/Scripts/Reward/RewardView.cs"
        start_and_implement(project, archive, "solo", edit_rel=rel)
        path = project / rel
        outside = (project / "Assets/Outside.cs").write_text("keep", encoding="utf-8")
        _ = outside
        before = path.read_text(encoding="utf-8")
        interrupt_slice(project, "feat", "impl-1")
        assert path.read_text(encoding="utf-8") == "// base\n"
        assert (project / "Assets/Outside.cs").read_text(encoding="utf-8") == "keep"
        assert read_lease(project, "feat") is None


def test_interrupt_fails_when_circuit_open() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-circuit-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        open_circuit(project, "feat", "impl-1", "dependency-lost", "dep gone", now=fixed_now("2026-10-27T13:40:00+00:00"))
        with pytest.raises(DeliveryError):
            interrupt_slice(project, "feat", "impl-1")
