from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.cli import dispatch
from bulings.delivery.archive import delivery_status, init_delivery
from bulings.delivery.documents import confirm_change, read_managed_document
from bulings.delivery.errors import DeliveryError
from bulings.delivery.frontmatter import render_frontmatter
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import approve_requirements, cold_read_prompt
from bulings.install import package_root


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _valid_requirements_body(source_rel: str) -> str:
    return f"""
# 需求

## 当前决定

无

## 场景

### 玩家靠近建筑

- 主体：玩家
- 初始条件：建筑在场景内
- 操作：靠近到交互距离
- 可观察结果：出现交互提示
- 来源：{source_rel}#L1

## 非目标

不做联机同步
"""


def _write_requirements(archive: Path, project: Path, source_rel: str) -> None:
    path = archive / "01-requirements" / "README.md"
    meta, _ = read_managed_document(path)
    body = _valid_requirements_body(source_rel)
    path.write_text(
        render_frontmatter(meta, body if body.startswith("\n") else "\n" + body),
        encoding="utf-8",
        newline="\n",
    )
    (project / source_rel).parent.mkdir(parents=True, exist_ok=True)
    (project / source_rel).write_text("策划\n", encoding="utf-8")


def test_approve_requirements_success(capsys) -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-req-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "building-interaction", "建筑交互", now=_fixed_now(stamp))
        archive = project / ".bulings" / "deliveries" / "building-interaction"
        _write_requirements(archive, project, "Assets/design.md")
        confirm_change(
            project,
            "building-interaction",
            [
                document_id("building-interaction", "requirements.terminology"),
                document_id("building-interaction", "requirements.overview"),
            ],
            False,
            now=_fixed_now(stamp),
        )
        record = approve_requirements(
            project,
            "building-interaction",
            "approve",
            "对话 14:22",
            "按这个范围做",
            now=_fixed_now(stamp),
        )
        feature = json.loads((archive / "feature.json").read_text(encoding="utf-8"))
        assert feature["lifecycle"] == "active"
        assert feature["approvals"]["requirements"]["userConfirmation"] == "按这个范围做"
        assert record["locator"] == "对话 14:22"

        code = dispatch(
            [
                "delivery",
                "status",
                "--project",
                str(project),
                "--feature-id",
                "building-interaction",
            ]
        )
        assert code == 0
        status = json.loads(capsys.readouterr().out)
        assert status["approvalState"]["requirements"] == "approved"


def test_approve_rejects_and_keeps_feature_json(capsys) -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-req-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "feat", "功能", now=_fixed_now(stamp))
        archive = project / ".bulings" / "deliveries" / "feat"
        feature_path = archive / "feature.json"
        before = feature_path.read_bytes()

        with pytest.raises(DeliveryError):
            approve_requirements(project, "feat", "approve", "loc", "确认", now=_fixed_now(stamp))
        assert feature_path.read_bytes() == before

        _write_requirements(archive, project, "Assets/design.md")
        body = _valid_requirements_body("待提供：策划案").replace("Assets/design.md#L1", "待提供：策划案")
        path = archive / "01-requirements" / "README.md"
        meta, _ = read_managed_document(path)
        path.write_text(render_frontmatter(meta, body), encoding="utf-8", newline="\n")
        confirm_change(
            project,
            "feat",
            [
                document_id("feat", "requirements.terminology"),
                document_id("feat", "requirements.overview"),
            ],
            False,
            now=_fixed_now(stamp),
        )
        with pytest.raises(DeliveryError):
            approve_requirements(project, "feat", "approve", "loc", "确认", now=_fixed_now(stamp))
        assert feature_path.read_bytes() == before


def test_approval_becomes_stale_after_semantic_change() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-req-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "feat", "功能", now=_fixed_now(stamp))
        archive = project / ".bulings" / "deliveries" / "feat"
        _write_requirements(archive, project, "Assets/design.md")
        confirm_change(
            project,
            "feat",
            [
                document_id("feat", "requirements.terminology"),
                document_id("feat", "requirements.overview"),
            ],
            False,
            now=_fixed_now(stamp),
        )
        approve_requirements(project, "feat", "approve", "loc", "确认", now=_fixed_now(stamp))
        readme = archive / "01-requirements" / "README.md"
        meta, body = read_managed_document(readme)
        readme.write_text(
            render_frontmatter(meta, body.replace("出现交互提示", "出现交互提示（改）")),
            encoding="utf-8",
            newline="\n",
        )
        confirm_change(
            project,
            "feat",
            [document_id("feat", "requirements.overview")],
            True,
            now=_fixed_now("2026-10-27T01:00:00+00:00"),
        )
        detail = delivery_status(project, "feat")
        assert detail.approval_state["requirements"] == "stale"


def test_cold_read_prompt_content() -> None:
    stamp = "2026-10-27T00:00:00+00:00"
    with tempfile.TemporaryDirectory(prefix="bulings-req-") as directory:
        project = Path(directory)
        _unity_project(project)
        init_delivery(project, "building-interaction", "建筑交互", now=_fixed_now(stamp))
        archive = project / ".bulings" / "deliveries" / "building-interaction"
        _write_requirements(archive, project, "Assets/design.md")
        result = cold_read_prompt(project, "building-interaction", "范围是否闭合？")
        assert "范围是否闭合？" in result.prompt
        for word in ("直接说明", "只能推断", "没有说明", "存在歧义"):
            assert word in result.prompt
        impl_text = (archive / "05-implementation" / "README.md").read_text(encoding="utf-8")
        assert impl_text not in result.prompt


def test_rules_requirements_reference(capsys) -> None:
    import hashlib

    ref = package_root() / "pack" / "skills" / "delivery" / "references" / "requirements.md"
    raw = ref.read_bytes()
    with tempfile.TemporaryDirectory(prefix="bulings-req-") as directory:
        project = Path(directory)
        _unity_project(project)
        code = dispatch(["delivery", "rules", "--project", str(project), "--action", "requirements"])
        assert code == 0
        rule = json.loads(capsys.readouterr().out)["rules"][0]
        assert "场景" in rule["body"]
        assert "待提供" in rule["body"]
        assert rule["sha256"] == f"sha256:{hashlib.sha256(raw).hexdigest()}"
        assert rule["body"] == raw.decode("utf-8")
