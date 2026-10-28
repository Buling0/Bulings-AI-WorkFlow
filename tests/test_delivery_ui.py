from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from bulings.delivery.archive import init_delivery
from bulings.delivery.errors import DeliveryError
from bulings.delivery.freeze_flow import begin_validation, freeze_delivery, record_validation
from bulings.delivery.ui_flow import (
    approve_final,
    approve_ui_baseline,
    check_ui_baseline,
    prepare_ui_baseline,
    publish_ui,
    record_acceptance,
)
from tests.delivery_helpers import fixed_now, unity_git
from tests.test_delivery_design import _write_md
from tests.test_delivery_freeze import _validation_body


def _ui_baseline_ready(project: Path, archive: Path) -> None:
    prepare_ui_baseline(project, "feat")
    path = archive / "02-investigation/ui-baseline.json"
    payload = {
        "schema": 1,
        "items": [
            {
                "scenario": "玩家靠近建筑",
                "prefabs": [{"status": "verified", "path": "Assets/UI/Reward.prefab", "purpose": "按钮"}],
                "protocols": [{"status": "not_applicable", "purpose": "无"}],
                "configurations": [{"status": "inherited", "path": "Assets/Config/Reward.json", "purpose": "表"}],
                "requirement": {"status": "verified", "purpose": "点击领取"},
            }
        ],
        "excludedSources": [],
    }
    (project / "Assets/UI").mkdir(parents=True, exist_ok=True)
    (project / "Assets/UI/Reward.prefab").write_text("prefab", encoding="utf-8")
    (project / "Assets/Config").mkdir(parents=True, exist_ok=True)
    (project / "Assets/Config/Reward.json").write_text("{}", encoding="utf-8")
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")


def test_missing_prefab_not_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-ui-") as directory:
        project = Path(directory)
        unity_git(project)
        init_delivery(project, "feat", "ui feat", profile="ui", now=fixed_now("2026-10-27T08:00:00+00:00"))
        prepare_ui_baseline(project, "feat")
        archive = project / ".bulings/deliveries/feat"
        path = archive / "02-investigation/ui-baseline.json"
        path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "items": [
                        {
                            "scenario": "玩家靠近建筑",
                            "prefabs": [{"status": "missing", "purpose": "缺 prefab"}],
                            "protocols": [{"status": "not_applicable", "purpose": "无"}],
                            "configurations": [{"status": "not_applicable", "purpose": "无"}],
                            "requirement": {"status": "verified", "purpose": "x"},
                        }
                    ],
                    "excludedSources": [],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        row = check_ui_baseline(project, "feat")[0]
        assert row["ready"] is False
        with pytest.raises(DeliveryError):
            approve_ui_baseline(
                project,
                "feat",
                ["玩家靠近建筑"],
                "approve",
                "chat",
                "ok",
                now=fixed_now("2026-10-27T09:00:00+00:00"),
            )


def test_static_acceptance_not_delivery_ready() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-ui-") as directory:
        project = Path(directory)
        unity_git(project)
        init_delivery(project, "feat", "ui feat", profile="ui", now=fixed_now("2026-10-27T08:00:00+00:00"))
        archive = project / ".bulings/deliveries/feat"
        _ui_baseline_ready(project, archive)
        record_acceptance(
            project,
            "feat",
            {
                "schema": 1,
                "smoke": {"status": "unverified", "entry": "main", "note": ""},
                "scenarios": [{"scenario": "玩家靠近建筑", "level": "static", "status": "unverified", "actual": "", "evidence": []}],
            },
        )
        pub = publish_ui(project, "feat")
        assert pub["deliveryReady"] is False
