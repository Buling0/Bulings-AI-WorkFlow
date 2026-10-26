from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bulings.config import workflow_file


@dataclass(frozen=True)
class InstallResult:
    config_written: bool


def package_root() -> Path:
    start = Path(__file__).resolve().parent
    for candidate in (start.parent, *start.parents):
        skills = candidate / "pack" / "skills"
        example = candidate / "pack" / "profiles" / "workflow.example.yaml"
        if skills.is_dir() and example.is_file():
            return candidate
    raise FileNotFoundError("找不到 pack/skills。请在仓库根目录执行 pip install -e .")


def is_unity_project(project_root: str | os.PathLike[str]) -> bool:
    root = Path(project_root)
    return (root / "Assets").is_dir() and (root / "ProjectSettings").is_dir()


def install_workflow(project_root: str | os.PathLike[str]) -> InstallResult:
    root = Path(project_root)
    if not is_unity_project(root):
        raise RuntimeError(f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {root}")

    skills_source = package_root() / "pack" / "skills"
    skills_dest = root / ".cursor" / "skills"
    skills_dest.mkdir(parents=True, exist_ok=True)
    for entry in skills_source.iterdir():
        if not entry.is_dir():
            continue
        destination = skills_dest / entry.name
        if destination.is_dir():
            shutil.rmtree(destination)
        elif destination.exists():
            destination.unlink()
        shutil.copytree(entry, destination)

    config_dest = workflow_file(root)
    if config_dest.exists():
        return InstallResult(config_written=False)

    config_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(package_root() / "pack" / "profiles" / "workflow.example.yaml", config_dest)
    return InstallResult(config_written=True)
