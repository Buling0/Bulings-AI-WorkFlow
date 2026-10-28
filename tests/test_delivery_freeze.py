from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bulings.delivery.archive import delivery_status
from bulings.delivery.documents import confirm_change
from bulings.delivery.errors import DeliveryError
from bulings.delivery.freeze_flow import begin_validation, freeze_delivery, record_validation
from bulings.delivery.paths import document_id
from bulings.delivery.circuit_flow import open_circuit
from tests.delivery_helpers import bootstrap_plan, fixed_now, start_and_implement, submit_and_pass
from tests.test_delivery_design import _write_md


def _validation_body() -> str:
    return """
# 验证

## 场景结果

### 玩家靠近建筑

- 实际结果：正常
- 证据：Assets/Scripts/Reward/RewardView.cs#1
- 偏差：无

## 未验证边界

无

## 残留风险

无

## 后续接入

无
"""


def test_begin_validation_requires_all_slices() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-freeze-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        with pytest.raises(DeliveryError) as error:
            begin_validation(project, "feat", now=fixed_now("2026-10-27T16:00:00+00:00"))
        assert error.value.code == "SLICES_INCOMPLETE"


def test_freeze_after_full_validation() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-freeze-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        submit_and_pass(project)
        _write_md(archive, "06-validation/README.md", _validation_body())
        begin_validation(project, "feat", now=fixed_now("2026-10-27T16:00:00+00:00"))
        record_validation(project, "feat", "passed", "none", "none", now=fixed_now("2026-10-27T16:30:00+00:00"))
        status1 = freeze_delivery(project, "feat", now=fixed_now("2026-10-27T17:00:00+00:00"))
        assert status1 == "frozen"
        frozen_at = json.loads((archive / "feature.json").read_text(encoding="utf-8"))["frozenAt"]
        status2 = freeze_delivery(project, "feat", now=fixed_now("2026-10-27T18:00:00+00:00"))
        assert status2 == "unchanged"
        assert json.loads((archive / "feature.json").read_text(encoding="utf-8"))["frozenAt"] == frozen_at


def test_workspace_drift_blocks_record() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-freeze-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        submit_and_pass(project)
        _write_md(archive, "06-validation/README.md", _validation_body())
        begin_validation(project, "feat", now=fixed_now("2026-10-27T16:00:00+00:00"))
        (project / "Assets/Scripts/Reward/RewardView.cs").write_text("// drift\n", encoding="utf-8")
        with pytest.raises(DeliveryError) as error:
            record_validation(project, "feat", "passed", "none", "none", now=fixed_now("2026-10-27T16:30:00+00:00"))
        assert error.value.code == "WORKSPACE_DRIFT"


def test_completion_blocked_with_circuit() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-freeze-") as directory:
        project = Path(directory)
        archive = bootstrap_plan(project)
        start_and_implement(project, archive, "solo")
        open_circuit(project, "feat", "impl-1", "invariant-broken", "x", now=fixed_now("2026-10-27T13:40:00+00:00"))
        status = delivery_status(project, "feat")
        assert status.completion["claim"] == "blocked"
