from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.delivery.archive import delivery_status
from bulings.delivery.design_flow import prepare_design, record_design_review
from bulings.delivery.documents import confirm_change
from bulings.delivery.errors import DeliveryError
from bulings.delivery.paths import document_id
from bulings.delivery.slice_plan import approve_slice_plan, check_slice_plan, prepare_plan, prepare_slice_plan
from tests.test_delivery_design import _bootstrap_approved, _design_internal, _unity_project, _write_md


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _confirm_docs(project: Path, feature_id: str, stamp: str, docs: list[str]) -> None:
    confirm_change(project, feature_id, docs, False, now=_fixed_now(stamp))


def _plan_body(slice_lines: str) -> str:
    return f"""
# 计划

## 拆分

{slice_lines}

## 共同依赖

无
"""


def _bootstrap_plan_ready(project: Path, feature_id: str = "feat") -> Path:
    archive = _bootstrap_approved(project, feature_id)
    _write_md(archive, "03-design/README.md", _design_internal())
    prepare_design(project, feature_id)
    _confirm_docs(
        project,
        feature_id,
        "2026-10-27T08:00:00+00:00",
        [
            document_id(feature_id, "requirements.terminology"),
            document_id(feature_id, "requirements.overview"),
            document_id(feature_id, "investigation.overview"),
            document_id(feature_id, "design.overview"),
        ],
    )
    record_design_review(project, feature_id, "pass", "ok", now=_fixed_now("2026-10-27T08:00:00+00:00"))
    prepare_plan(project, feature_id)
    return archive


def _write_plan_and_slices(
    archive: Path,
    project: Path,
    feature_id: str,
    plan_slices: str,
    slices: list[dict[str, object]],
) -> None:
    _write_md(archive, "04-plan/README.md", _plan_body(plan_slices))
    _confirm_docs(
        project,
        feature_id,
        "2026-10-27T09:00:00+00:00",
        [document_id(feature_id, "plan.overview")],
    )
    prepare_slice_plan(project, feature_id)
    path = archive / "04-plan" / "slice-plan.json"
    path.write_text(
        json.dumps({"schema": 1, "featureId": feature_id, "version": 1, "slices": slices}, indent=2)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )


def test_two_independent_slices_ready_and_waiting() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-slice-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_plan_ready(project)
        plan = """
- 结果：A
  切片：slice-a
  场景：玩家靠近建筑
  理由：独立
- 结果：B
  切片：slice-b
  场景：玩家靠近建筑
  理由：独立
"""
        slices = [
            {"id": "slice-a", "title": "A", "dependsOn": [], "replaces": []},
            {"id": "slice-b", "title": "B", "dependsOn": ["slice-a"], "replaces": []},
        ]
        _write_plan_and_slices(archive, project, "feat", plan, slices)
        check = check_slice_plan(project, "feat")
        approve_slice_plan(project, "feat", check.digest, now=_fixed_now("2026-10-27T10:00:00+00:00"))
        detail = delivery_status(project, "feat")
        assert detail.slice_eligibility["slice-a"] == "ready"
        assert detail.slice_eligibility["slice-b"] == "waiting"


def test_cycle_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-slice-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_plan_ready(project)
        plan = """
- 结果：A
  切片：a
  场景：玩家靠近建筑
  理由：x
- 结果：B
  切片：b
  场景：玩家靠近建筑
  理由：y
"""
        slices = [
            {"id": "a", "title": "A", "dependsOn": ["b"], "replaces": []},
            {"id": "b", "title": "B", "dependsOn": ["a"], "replaces": []},
        ]
        _write_plan_and_slices(archive, project, "feat", plan, slices)
        with pytest.raises(DeliveryError) as error:
            check_slice_plan(project, "feat")
        assert any(item.code == "SLICE_CYCLE" for item in error.value.blockers)


def test_plan_mismatch() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-slice-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_plan_ready(project)
        plan = """
- 结果：A
  切片：only-plan
  场景：玩家靠近建筑
  理由：x
"""
        slices = [
            {"id": "only-plan", "title": "A", "dependsOn": [], "replaces": []},
            {"id": "extra", "title": "E", "dependsOn": [], "replaces": []},
        ]
        _write_plan_and_slices(archive, project, "feat", plan, slices)
        with pytest.raises(DeliveryError) as error:
            check_slice_plan(project, "feat")
        assert any(item.code == "PLAN_MISMATCH" for item in error.value.blockers)


def test_approve_digest_mismatch_and_version_bump_history() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-slice-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_plan_ready(project)
        plan = """
- 结果：A
  切片：solo
  场景：玩家靠近建筑
  理由：x
"""
        slices = [{"id": "solo", "title": "S", "dependsOn": [], "replaces": []}]
        _write_plan_and_slices(archive, project, "feat", plan, slices)
        check = check_slice_plan(project, "feat")
        approve_slice_plan(project, "feat", check.digest, now=_fixed_now("2026-10-27T11:00:00+00:00"))
        approved = archive / "04-plan" / "slice-plan.approved.json"
        assert approved.is_file()

        path = archive / "04-plan" / "slice-plan.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["slices"][0]["title"] = "changed"
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        with pytest.raises(DeliveryError) as mismatch:
            approve_slice_plan(project, "feat", check.digest)
        assert mismatch.value.code == "DIGEST_MISMATCH"
        assert not (archive / "04-plan" / "history").exists()

        data["version"] = 2
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
        check2 = check_slice_plan(project, "feat")
        approve_slice_plan(project, "feat", check2.digest, now=_fixed_now("2026-10-27T12:00:00+00:00"))
        assert (archive / "04-plan" / "history" / "slice-plan-v1.json").is_file()
        detail = delivery_status(project, "feat")
        assert detail.slice_plan is not None
        assert detail.slice_plan["version"] == 2


def test_design_not_ready_blocks_check() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-slice-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(archive, "03-design/README.md", "\n# 设计\n\n待填写。\n")
        plan_path = archive / "04-plan" / "slice-plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps({"schema": 1, "featureId": "feat", "version": 1, "slices": []}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(DeliveryError) as error:
            check_slice_plan(project, "feat")
        assert error.value.code == "DESIGN_NOT_READY"
        assert not (archive / "04-plan" / "slice-plan.approved.json").exists()
