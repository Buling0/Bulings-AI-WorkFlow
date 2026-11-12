import tempfile
from pathlib import Path

import pytest

from bulings.install import install_workflow


def _unity_project(root: Path) -> None:
    (root / "Assets").mkdir()
    (root / "ProjectSettings").mkdir()


def test_init_overwrites_skills_and_keeps_existing_workflow() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-install-") as directory:
        project = Path(directory)
        _unity_project(project)

        first = install_workflow(project)
        assert first.config_written is True
        skill_path = project / ".cursor" / "skills" / "work-feature" / "SKILL.md"
        indie_path = project / ".cursor" / "skills" / "indie-feature" / "SKILL.md"
        config_path = project / ".bulings" / "workflow.yaml"
        assert skill_path.is_file()
        assert indie_path.is_file()
        assert "mode: work" in config_path.read_text(encoding="utf-8")
        assert "独游" in config_path.read_text(encoding="utf-8")
        assert "GameDesigns" in config_path.read_text(encoding="utf-8")
        assert "策划案" in skill_path.read_text(encoding="utf-8")
        assert "建立框架" in indie_path.read_text(encoding="utf-8")
        for name in ("frameworks.md", "framework-template.md", "slice-spec-template.md", "feature-doc-template.md"):
            assert (indie_path.parent / name).is_file()
        design_skill = project / ".cursor" / "skills" / "indie-design" / "SKILL.md"
        assert design_skill.is_file()
        assert "选项" in design_skill.read_text(encoding="utf-8")
        for name in ("dimensions.md", "design-template.md"):
            assert (design_skill.parent / name).is_file()

        config_path.write_text("mode: indie\n", encoding="utf-8")
        skill_path.write_text("stale\n", encoding="utf-8")

        second = install_workflow(project)
        assert second.config_written is False
        assert config_path.read_text(encoding="utf-8") == "mode: indie\n"
        installed_skill = skill_path.read_text(encoding="utf-8")
        assert installed_skill != "stale\n"
        assert "策划案" in installed_skill


def test_init_rejects_a_directory_that_is_not_a_unity_project() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-not-unity-") as directory:
        with pytest.raises(RuntimeError, match="Unity 工程"):
            install_workflow(directory)


def test_init_merges_unity_mcp_without_overwriting() -> None:
    import json

    with tempfile.TemporaryDirectory(prefix="bulings-mcp-") as directory:
        project = Path(directory)
        _unity_project(project)
        mcp_path = project / ".cursor" / "mcp.json"
        mcp_path.parent.mkdir()
        mcp_path.write_text(json.dumps({"mcpServers": {"other": {"url": "http://x"}}}), encoding="utf-8")

        first = install_workflow(project)
        assert first.mcp_written is True
        servers = json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]
        assert servers["other"] == {"url": "http://x"}
        assert servers["unity"]["url"].startswith("http://")
        assert (project / ".cursor" / "skills" / "client-split" / "SKILL.md").is_file()

        servers["unity"] = {"url": "http://custom"}
        mcp_path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")
        assert install_workflow(project).mcp_written is False
        assert json.loads(mcp_path.read_text(encoding="utf-8"))["mcpServers"]["unity"] == {"url": "http://custom"}


def test_init_skips_mcp_when_disabled() -> None:
    with tempfile.TemporaryDirectory(prefix="bulings-mcp-off-") as directory:
        project = Path(directory)
        _unity_project(project)
        (project / ".bulings").mkdir()
        (project / ".bulings" / "workflow.yaml").write_text("unity:\n  mcp:\n    enabled: false\n", encoding="utf-8")
        assert install_workflow(project).mcp_written is False
        assert not (project / ".cursor" / "mcp.json").exists()
