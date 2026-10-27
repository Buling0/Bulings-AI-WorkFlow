from __future__ import annotations

import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from bulings.cli import dispatch
from bulings.delivery.archive import init_delivery
from bulings.install import install_workflow, package_root


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _skill_front_matter(skill_path: Path) -> dict[str, object]:
    text = skill_path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert match is not None
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict)
    return data


def test_delivery_skill_file_has_explicit_description_and_disable_invocation() -> None:
    skill_path = package_root() / "pack" / "skills" / "delivery" / "SKILL.md"
    assert skill_path.is_file()
    meta = _skill_front_matter(skill_path)
    assert meta.get("name") == "delivery"
    assert meta.get("disable-model-invocation") is True
    description = str(meta.get("description", ""))
    assert "显式" in description


def test_rules_coordinator_matches_file_bytes(capsys) -> None:
    rule_path = package_root() / "pack" / "skills" / "delivery" / "references" / "coordinator.md"
    raw = rule_path.read_bytes()
    expected_sha = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    with tempfile.TemporaryDirectory(prefix="bulings-skill-") as directory:
        project = Path(directory)
        _unity_project(project)
        code = dispatch(["delivery", "rules", "--project", str(project), "--action", "coordinator"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["action"] == "coordinator"
        assert len(payload["rules"]) == 1
        rule = payload["rules"][0]
        assert rule["path"] == "pack/skills/delivery/references/coordinator.md"
        assert rule["sha256"] == expected_sha
        assert rule["body"] == raw.decode("utf-8")


def test_unknown_action_fails_with_empty_stdout(capsys) -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-skill-") as directory:
        project = Path(directory)
        _unity_project(project)
        code = dispatch(["delivery", "rules", "--project", str(project), "--action", "missing-action"])
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        err = json.loads(captured.err)
        assert err["code"] == "UNKNOWN_ACTION"


def test_open_multiple_substring_matches(capsys) -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-skill-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "feat-a", "建筑交互 Alpha", now=_fixed_now(stamp))
        init_delivery(project, "feat-b", "建筑交互 Beta", now=_fixed_now(stamp))
        code = dispatch(["delivery", "open", "--project", str(project), "--query", "建筑交互"])
        assert code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        err = json.loads(captured.err)
        assert err["code"] == "MULTIPLE_MATCHES"
        assert len(err["candidates"]) == 2


def test_open_feature_id_exact_beats_title_substring(capsys) -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-skill-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "shared-token", "标题含 shared-token 字样", now=_fixed_now(stamp))
        init_delivery(project, "other", "无关", now=_fixed_now(stamp))
        code = dispatch(["delivery", "open", "--project", str(project), "--query", "shared-token"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["match"] == "unique"
        assert payload["featureId"] == "shared-token"


def test_init_installs_delivery_skill_alongside_work_feature() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-skill-") as directory:
        project = Path(directory)
        _unity_project(project)
        install_workflow(project)
        delivery_skill = project / ".cursor" / "skills" / "delivery" / "SKILL.md"
        work_skill = project / ".cursor" / "skills" / "work-feature" / "SKILL.md"
        assert delivery_skill.is_file()
        assert work_skill.is_file()
        assert _skill_front_matter(delivery_skill)["name"] == "delivery"
