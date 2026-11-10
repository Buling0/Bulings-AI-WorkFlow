from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bulings.config import UnityMcpConfig, load_workflow_config, workflow_file


@dataclass(frozen=True)
class InstallResult:
    config_written: bool
    mcp_written: bool = False


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
    config_written = False
    if not config_dest.exists():
        config_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package_root() / "pack" / "profiles" / "workflow.example.yaml", config_dest)
        config_written = True

    mcp_written = install_unity_mcp(root, load_workflow_config(root).unity_mcp)
    return InstallResult(config_written=config_written, mcp_written=mcp_written)


def mcp_server_entry(mcp: UnityMcpConfig) -> dict[str, object] | None:
    if mcp.command.strip():
        return {"command": mcp.command, "args": list(mcp.args)}
    if mcp.url.strip():
        return {"url": mcp.url}
    return None


def install_unity_mcp(root: Path, mcp: UnityMcpConfig) -> bool:
    """把 Unity MCP 合并写入 <工程>/.cursor/mcp.json，只动 mcp.server 这一项。

    已存在同名条目时不覆盖（用户可能手改过）；文件无法解析时不动它。
    """
    entry = mcp_server_entry(mcp)
    if not mcp.enabled or entry is None:
        return False
    target = root / ".cursor" / "mcp.json"
    data: dict[str, object] = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        if not isinstance(loaded, dict):
            return False
        data = loaded
    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict) or mcp.server in servers:
        return False
    servers[mcp.server] = entry
    data["mcpServers"] = servers
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return True
