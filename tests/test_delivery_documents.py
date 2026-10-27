from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from bulings.delivery.archive import init_delivery
from bulings.delivery.documents import (
    assert_fresh,
    body_fingerprint,
    confirm_change,
    read_managed_document,
    refresh_queue,
)
from bulings.delivery.errors import DeliveryError
from bulings.delivery.frontmatter import render_frontmatter
from bulings.delivery.paths import document_id


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def _fixed_now(stamp: str):
    parsed = datetime.fromisoformat(stamp)

    def now() -> datetime:
        return parsed

    return now


def _init(project: Path, feature_id: str = "building-interaction") -> Path:
    init_delivery(project, feature_id, "建筑交互", now=_fixed_now("2026-10-27T00:00:00+00:00"))
    return project / ".bulings" / "deliveries" / feature_id


def _doc_id(feature_id: str, suffix: str) -> str:
    return document_id(feature_id, suffix)


def _write_body(archive: Path, rel: str, body: str) -> None:
    path = archive / rel
    meta, _old = read_managed_document(path)
    normalized = body if body.startswith("\n") else "\n" + body
    path.write_text(render_frontmatter(meta, normalized), encoding="utf-8", newline="\n")


def _set_dependencies(archive: Path, rel: str, dependencies: list[str], versions: dict[str, str]) -> None:
    path = archive / rel
    meta, body = read_managed_document(path)
    meta["dependencies"] = dependencies
    meta["dependencyVersions"] = versions
    path.write_text(render_frontmatter(meta, body if body.startswith("\n") else "\n" + body), encoding="utf-8", newline="\n")


def test_new_archive_requirements_depends_on_terminology_with_matching_fingerprint() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        term_id = _doc_id("building-interaction", "requirements.terminology")
        req_id = _doc_id("building-interaction", "requirements.overview")
        term_meta, term_body = read_managed_document(archive / "01-requirements/terminology.md")
        req_meta, req_body = read_managed_document(archive / "01-requirements/README.md")
        assert req_meta["dependencies"] == [term_id]
        assert req_meta["dependencyVersions"] == {term_id: "0.1.0"}
        assert term_meta["fingerprint"] == body_fingerprint(term_body)
        assert req_meta["fingerprint"] == body_fingerprint(req_body)


def test_semantic_terminology_stales_requirements_and_assert_fresh_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        term_id = _doc_id(fid, "requirements.terminology")
        req_id = _doc_id(fid, "requirements.overview")
        _write_body(archive, "01-requirements/terminology.md", "\n# 术语\n\n## 已确认术语\n\n## 候选术语\n\n改动了\n")
        confirm_change(project, fid, [term_id], True, now=_fixed_now("2026-10-27T01:00:00+00:00"))
        queue = refresh_queue(project, fid)
        assert [item.document_id for item in queue] == [req_id]
        with pytest.raises(DeliveryError) as error:
            assert_fresh(project, fid, [req_id])
        assert error.value.code == "STALE_DOCUMENT"
        term_meta, _ = read_managed_document(archive / "01-requirements/terminology.md")
        assert term_meta["semanticVersion"] == "0.1.1"


def test_requirements_non_semantic_confirm_leaves_terminology_bumped() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        term_id = _doc_id(fid, "requirements.terminology")
        req_id = _doc_id(fid, "requirements.overview")
        _write_body(archive, "01-requirements/terminology.md", "\n# 术语\n\n## 已确认术语\n\n## 候选术语\n\n改动了\n")
        confirm_change(project, fid, [term_id], True, now=_fixed_now("2026-10-27T01:00:00+00:00"))
        _write_body(archive, "01-requirements/README.md", "\n# 需求\n\n同步术语。\n")
        confirm_change(project, fid, [req_id], False, now=_fixed_now("2026-10-27T02:00:00+00:00"))
        assert refresh_queue(project, fid) == []
        term_meta, _ = read_managed_document(archive / "01-requirements/terminology.md")
        req_meta, _ = read_managed_document(archive / "01-requirements/README.md")
        assert term_meta["semanticVersion"] == "0.1.1"
        assert req_meta["semanticVersion"] == "0.1.0"
        assert req_meta["contentStatus"] == "draft"


def test_requirements_semantic_confirm_without_downstream_keeps_plan() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        req_id = _doc_id(fid, "requirements.overview")
        _write_body(archive, "01-requirements/README.md", "\n# 需求\n\n语义变更。\n")
        confirm_change(project, fid, [req_id], True, now=_fixed_now("2026-10-27T03:00:00+00:00"))
        plan_meta, _ = read_managed_document(archive / "04-plan/README.md")
        assert plan_meta["contentStatus"] == "draft"
        assert refresh_queue(project, fid) == []


def test_plan_depends_on_requirements_semantic_flow() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        req_id = _doc_id(fid, "requirements.overview")
        plan_id = _doc_id(fid, "plan.overview")
        impl_id = _doc_id(fid, "implementation.overview")
        _set_dependencies(archive, "04-plan/README.md", [req_id], {req_id: "0.1.0"})
        _set_dependencies(archive, "05-implementation/README.md", [plan_id], {plan_id: "0.1.0"})
        _write_body(archive, "01-requirements/README.md", "\n# 需求\n\n变更。\n")
        confirm_change(project, fid, [req_id], True, now=_fixed_now("2026-10-27T04:00:00+00:00"))
        plan_meta, _ = read_managed_document(archive / "04-plan/README.md")
        impl_meta, _ = read_managed_document(archive / "05-implementation/README.md")
        assert plan_meta["contentStatus"] == "stale"
        assert impl_meta["contentStatus"] == "draft"
        _write_body(archive, "04-plan/README.md", "\n# 计划\n\n跟进。\n")
        confirm_change(project, fid, [plan_id], False, now=_fixed_now("2026-10-27T05:00:00+00:00"))
        assert refresh_queue(project, fid) == []
        impl_meta, _ = read_managed_document(archive / "05-implementation/README.md")
        assert impl_meta["contentStatus"] == "draft"


def test_reject_self_dependency_backward_dependency_duplicate_term_and_frozen() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        inv_id = _doc_id(fid, "investigation.overview")
        plan_id = _doc_id(fid, "plan.overview")
        term_id = _doc_id(fid, "requirements.terminology")
        _set_dependencies(archive, "02-investigation/README.md", [plan_id], {plan_id: "0.1.0"})
        with pytest.raises(DeliveryError):
            confirm_change(project, fid, [inv_id], False)
        _set_dependencies(archive, "02-investigation/README.md", [inv_id], {inv_id: "0.1.0"})
        with pytest.raises(DeliveryError):
            confirm_change(project, fid, [inv_id], False)
        bad_body = (
            "\n# 术语\n\n## 已确认术语\n\n### 重复\n- 状态：已确认\n- 一句话定义：a\n\n"
            "## 候选术语\n\n### 重复\n- 状态：候选\n- 一句话定义：b\n"
        )
        _write_body(archive, "01-requirements/terminology.md", bad_body)
        from bulings.delivery.validation import validate_delivery

        errors = validate_delivery(archive, fid)
        assert any(error.code == "DUPLICATE_TERM" for error in errors)
        feature_path = archive / "feature.json"
        feature = json.loads(feature_path.read_text(encoding="utf-8"))
        feature["lifecycle"] = "frozen"
        feature_path.write_text(json.dumps(feature, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        with pytest.raises(DeliveryError) as frozen:
            confirm_change(project, fid, [term_id], False)
        assert frozen.value.code == "LIFECYCLE_FROZEN"


def test_repeat_confirm_returns_unchanged() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-doc-") as directory:
        project = Path(directory)
        _unity_project(project)
        archive = _init(project)
        fid = "building-interaction"
        term_id = _doc_id(fid, "requirements.terminology")
        feature_path = archive / "feature.json"
        before = feature_path.read_bytes()
        result = confirm_change(project, fid, [term_id], False, now=_fixed_now("2026-10-27T06:00:00+00:00"))
        assert result.status == "unchanged"
        assert feature_path.read_bytes() == before
