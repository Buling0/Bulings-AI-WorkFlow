from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.cli import dispatch
from bulings.delivery.archive import delivery_status, init_delivery, list_deliveries
from bulings.delivery.errors import DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.fingerprint import content_fingerprint
from bulings.delivery.paths import ARCHIVE_RELATIVE_PATHS


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def test_feature_id_rules() -> None:
    assert is_valid_feature_id("a")
    assert is_valid_feature_id("building-interaction")
    assert is_valid_feature_id("ab")
    assert not is_valid_feature_id("")
    assert not is_valid_feature_id("-x")
    assert not is_valid_feature_id("x-")
    assert not is_valid_feature_id("Building")
    assert not is_valid_feature_id("a" * 65)


def test_content_fingerprint() -> None:
    assert content_fingerprint("hello").startswith("sha256:")
    assert len(content_fingerprint("hello")) == len("sha256:") + 64


def test_init_creates_full_archive() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        result = init_delivery(
            project,
            "building-interaction",
            "  建筑交互  ",
            now=_fixed_now(stamp),
        )
        assert result.status == "created"
        archive = project / ".bulings" / "deliveries" / "building-interaction"
        assert archive.is_dir()
        for rel in ARCHIVE_RELATIVE_PATHS:
            assert (archive / rel).is_file()
        feature = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
        assert feature["schema"] == 1
        assert feature["featureId"] == "building-interaction"
        assert feature["title"] == "建筑交互"
        assert feature["profile"] == "delivery"
        assert feature["createdAt"] == stamp
        terminology = (archive / "01-requirements" / "terminology.md").read_text(encoding="utf-8")
        assert "# 术语" in terminology
        assert "## 已确认术语" in terminology
        assert "## 候选术语" in terminology


def test_second_init_is_unchanged() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "feat-a", "标题", now=_fixed_now(stamp))
        feature_path = project / ".bulings" / "deliveries" / "feat-a" / "feature.json"
        before_bytes = feature_path.read_bytes()
        before_mtime = feature_path.stat().st_mtime
        later = init_delivery(project, "feat-a", "别的标题", now=_fixed_now("2026-11-01T00:00:00+00:00"))
        assert later.status == "unchanged"
        assert feature_path.read_bytes() == before_bytes
        assert feature_path.stat().st_mtime == before_mtime


def test_init_rejects_invalid_inputs_without_creating_deliveries() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        with pytest.raises(DeliveryError) as bad_id:
            init_delivery(project, "Bad-ID", "标题", now=_fixed_now("2026-10-27T00:00:00+00:00"))
        assert bad_id.value.exit_code == 2
        assert not (project / ".bulings" / "deliveries").exists()

        with pytest.raises(DeliveryError) as bad_title:
            init_delivery(project, "ok-id", "   ", now=_fixed_now("2026-10-27T00:00:00+00:00"))
        assert bad_title.value.exit_code == 2

    with tempfile.TemporaryDirectory(prefix="bulings-not-unity-") as directory:
        project = Path(directory)
        with pytest.raises(DeliveryError) as not_unity:
            init_delivery(project, "ok-id", "标题", now=_fixed_now("2026-10-27T00:00:00+00:00"))
        assert not_unity.value.exit_code == 1


def test_init_does_not_repair_partial_archive() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "partial", "标题", now=_fixed_now(stamp))
        readme = project / ".bulings" / "deliveries" / "partial" / "03-design" / "README.md"
        readme.unlink()
        with pytest.raises(DeliveryError) as error:
            init_delivery(project, "partial", "标题", now=_fixed_now(stamp))
        assert error.value.code == "ARCHIVE_INVALID"
        assert not readme.exists()


def test_status_lists_valid_and_invalid() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "good-one", "好", now=_fixed_now(stamp))
        init_delivery(project, "good-two", "也好", now=_fixed_now(stamp))
        broken = project / ".bulings" / "deliveries" / "good-two" / "feature.json"
        broken.unlink()
        deliveries, invalid = list_deliveries(project)
        assert [item.feature_id for item in deliveries] == ["good-one"]
        assert invalid == ["good-two"]


def test_status_detail_and_cli_json(capsys) -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "building-interaction", "建筑交互", now=_fixed_now(stamp))
        detail = delivery_status(project, "building-interaction")
        assert detail.profile == "delivery"
        assert detail.lifecycle == "draft"
        assert detail.archive == ".bulings/deliveries/building-interaction"

        code = dispatch(
            [
                "delivery",
                "init",
                "--project",
                str(project),
                "--feature-id",
                "building-interaction",
                "--title",
                "建筑交互",
            ]
        )
        assert code == 0
        out = json.loads(capsys.readouterr().out)
        assert out["status"] == "unchanged"

        code = dispatch(["delivery", "status", "--project", str(project)])
        assert code == 0
        listed = json.loads(capsys.readouterr().out)
        assert len(listed["deliveries"]) == 1
        assert listed["invalid"] == []


def test_cli_invalid_feature_id_exit_code(capsys) -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-delivery-") as directory:
        project = Path(directory)
        _unity_project(project)
        code = dispatch(
            [
                "delivery",
                "init",
                "--project",
                str(project),
                "--feature-id",
                "Bad-ID",
                "--title",
                "x",
            ]
        )
        assert code == 2
        err = json.loads(capsys.readouterr().err)
        assert err["code"] == "INVALID_FEATURE_ID"
