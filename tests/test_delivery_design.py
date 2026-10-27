from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.cli import dispatch
from bulings.delivery.archive import delivery_status, init_delivery
from bulings.delivery.design_flow import (
    design_ready,
    design_review_prompt,
    prepare_design,
    record_design_review,
)
from bulings.delivery.documents import confirm_change, read_managed_document
from bulings.delivery.errors import DeliveryError
from bulings.delivery.frontmatter import render_frontmatter
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import approve_requirements


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _write_md(archive: Path, rel: str, body: str) -> None:
    path = archive / rel
    meta, _ = read_managed_document(path)
    normalized = body if body.startswith("\n") else "\n" + body
    path.write_text(render_frontmatter(meta, normalized), encoding="utf-8", newline="\n")


def _confirm_all(project: Path, feature_id: str, stamp: str) -> None:
    confirm_change(
        project,
        feature_id,
        [
            document_id(feature_id, "requirements.terminology"),
            document_id(feature_id, "requirements.overview"),
            document_id(feature_id, "investigation.overview"),
            document_id(feature_id, "design.overview"),
        ],
        False,
        now=_fixed_now(stamp),
    )


def _bootstrap_approved(project: Path, feature_id: str = "feat") -> Path:
    stamp = "2026-10-27T00:00:00+00:00"
    init_delivery(project, feature_id, "功能", now=_fixed_now(stamp))
    archive = project / ".bulings" / "deliveries" / feature_id
    (project / "Assets" / "evidence.md").write_text("e\n", encoding="utf-8")
    (project / "Assets" / "design.md").write_text("d\n", encoding="utf-8")
    _write_md(
        archive,
        "01-requirements/README.md",
        """
# 需求

## 当前决定

无

## 场景

### 玩家靠近建筑

- 主体：玩家
- 初始条件：在场景内
- 操作：靠近
- 可观察结果：提示
- 来源：Assets/design.md#L1

## 非目标

无
""",
    )
    _confirm_all(project, feature_id, stamp)
    approve_requirements(project, feature_id, "approve", "loc", "确认", now=_fixed_now(stamp))
    _write_md(
        archive,
        "02-investigation/README.md",
        """
# 调查

## 事实

### 已有交互距离

- 证据：Assets/evidence.md#L1
- 说明：配置存在

## 未知

无
""",
    )
    _confirm_all(project, feature_id, stamp)
    return archive


def _design_internal() -> str:
    return """
# 设计

## 方案

复用现有模块。

## 变化

### 整理命名

- 类型：内部整理
- 场景：玩家靠近建筑
- 行为：重命名私有方法
- 不变量：对外接口不变
"""


def _design_external() -> str:
    return """
# 设计

## 方案

新增提示流程。

## 变化

### 靠近提示

- 类型：外部行为
- 场景：玩家靠近建筑
- 行为：显示 UI 提示
- 不变量：不影响战斗
"""


def test_design_ready_internal_without_architecture_review() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(archive, "03-design/README.md", _design_internal())
        prepare_design(project, "feat", now=_fixed_now("2026-10-27T01:00:00+00:00"))
        _confirm_all(project, "feat", "2026-10-27T01:00:00+00:00")
        result = design_ready(project, "feat")
        assert result["status"] == "ready"


def test_design_ready_external_requires_review() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(archive, "03-design/README.md", _design_external())
        prepare_design(project, "feat")
        _confirm_all(project, "feat", "2026-10-27T02:00:00+00:00")
        with pytest.raises(DeliveryError) as error:
            design_ready(project, "feat")
        assert error.value.code == "NOT_READY"


def test_architecture_becomes_stale_after_semantic_change() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(archive, "03-design/README.md", _design_external())
        prepare_design(project, "feat")
        _confirm_all(project, "feat", "2026-10-27T03:00:00+00:00")
        record_design_review(project, "feat", "pass", "通过", now=_fixed_now("2026-10-27T03:00:00+00:00"))
        path = archive / "03-design/README.md"
        meta, body = read_managed_document(path)
        path.write_text(render_frontmatter(meta, body.replace("显示 UI 提示", "显示 UI 提示 v2")), encoding="utf-8", newline="\n")
        confirm_change(
            project,
            "feat",
            [document_id("feat", "design.overview")],
            True,
            now=_fixed_now("2026-10-27T04:00:00+00:00"),
        )
        detail = delivery_status(project, "feat")
        assert detail.approval_state["architecture"] == "stale"


def test_record_review_blocked_by_investigation() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(
            archive,
            "02-investigation/README.md",
            """
# 调查

## 事实

### 事实

- 证据：Assets/evidence.md#L1
- 说明：x

## 未知

### 性能上限

- 影响：设计
- 阻塞：是
""",
        )
        _confirm_all(project, "feat", "2026-10-27T05:00:00+00:00")
        with pytest.raises(DeliveryError) as error:
            record_design_review(project, "feat", "pass", "结论")
        assert error.value.code == "INVESTIGATION_BLOCKED"


def test_invalid_scene_after_prepare_design() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(
            archive,
            "03-design/README.md",
            """
# 设计

## 方案

x

## 变化

### 变化

- 类型：内部整理
- 场景：不存在的场景
- 行为：y
- 不变量：z
""",
        )
        prepare_design(project, "feat")
        _confirm_all(project, "feat", "2026-10-27T06:00:00+00:00")
        with pytest.raises(DeliveryError) as error:
            design_ready(project, "feat")
        assert any(item.code == "INVALID_DESIGN" for item in error.value.blockers)


def test_design_review_prompt_materials(capsys) -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-design-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _bootstrap_approved(project)
        _write_md(archive, "03-design/README.md", _design_external())
        prepare_design(project, "feat")
        _confirm_all(project, "feat", "2026-10-27T07:00:00+00:00")
        result = design_review_prompt(project, "feat")
        assert "01-requirements/README.md" in result.prompt
        assert "02-investigation/README.md" in result.prompt
        assert "03-design/README.md" in result.prompt
        assert "05-implementation" not in result.prompt
        assert "pass" in result.prompt and "fail" in result.prompt and "unverified" in result.prompt

        code = dispatch(["delivery", "design-review-prompt", "--project", str(project), "--feature-id", "feat"])
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload["materials"]) == 3
