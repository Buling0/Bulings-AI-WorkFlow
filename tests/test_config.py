import os
import tempfile
from pathlib import Path

from bulings.config import (
    RunOverrides,
    feature_token,
    load_workflow_config,
    merge_config,
    resolve_doc_path,
    resolve_run_config,
)
from bulings.install import is_unity_project


def test_missing_config_uses_defaults() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-config-") as directory:
        config = load_workflow_config(directory)
    assert config.mode == "work"
    assert config.model == "composer-2.5"
    assert config.docs.dev_spec.enabled is True
    assert config.docs.dev_spec.path == "Docs/AI/DevSpecs/{feature}.md"
    assert config.project.code_roots == []
    assert config.project.architecture == ""


def test_partial_config_merges_and_keeps_empty_fields() -> None:
    config = merge_config(
        {
            "mode": "indie",
            "docs": {"devSpec": {"enabled": False}},
            "project": {"namespaces": ["Game.UI"], "ui": {"framework": "UGUI"}},
        }
    )
    assert config.mode == "indie"
    assert config.docs.dev_spec.enabled is False
    assert config.docs.dev_spec.path == "Docs/AI/DevSpecs/{feature}.md"
    assert config.docs.feature_doc.enabled is True
    assert config.project.namespaces == ["Game.UI"]
    assert config.project.ui.framework == "UGUI"
    assert config.project.ui.binding == ""
    assert config.project.protected_paths == []


def test_feature_token_expands_doc_paths() -> None:
    root = os.path.join("C:\\", "unity", "game")
    config = merge_config({"docs": {"featureDoc": {"path": "Docs/{feature}/说明.md"}}})
    resolved = resolve_run_config(
        config,
        root,
        "背包",
        RunOverrides(dev_spec_path="Custom/{feature}.md", no_dev_spec=True),
    )
    assert resolved.feature == "背包"
    assert resolved.dev_spec_enabled is False
    assert resolved.feature_doc_enabled is True
    assert resolved.feature_doc_path == os.path.normpath(os.path.join(root, "Docs", "背包", "说明.md"))
    assert resolve_doc_path("Notes/{feature}.md", feature_token("背包/系统"), root) == os.path.normpath(
        os.path.join(root, "Notes", "背包-系统.md")
    )


def test_unity_project_needs_assets_and_project_settings() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-unity-") as directory:
        root = Path(directory)
        assert is_unity_project(root) is False
        (root / "Assets").mkdir()
        assert is_unity_project(root) is False
        (root / "ProjectSettings").write_text("not-a-directory", encoding="utf-8")
        assert is_unity_project(root) is False
        (root / "ProjectSettings").unlink()
        (root / "ProjectSettings").mkdir()
        assert is_unity_project(root) is True
