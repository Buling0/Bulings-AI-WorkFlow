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
        assert "策划案" in skill_path.read_text(encoding="utf-8")
        assert "本版本未实现，停止，不要擅自开工。" in indie_path.read_text(encoding="utf-8")

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
