from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WorkflowMode = str
DEFAULT_MODEL = "composer-2.5"
DEFAULT_DEV_SPEC = "Docs/AI/DevSpecs/{feature}.md"
DEFAULT_FEATURE_DOC = "Docs/AI/Features/{feature}.md"
DEFAULT_CLIENT_SPEC = "Docs/AI/ClientSpecs/{feature}.md"
DEFAULT_KNOWLEDGE_ROOT = "Docs/AI/Knowledge"
DEFAULT_MCP_SERVER = "unity"
DEFAULT_MCP_URL = "http://localhost:8080/mcp"
DEFAULT_FRAMEWORK_PLAN = ".bulings/indie/framework.json"
DEFAULT_FRAMEWORK_DOC = "Docs/AI/Frameworks/{game}.md"
DEFAULT_GDD = "Docs/AI/GameDesigns/{feature}.md"
DEFAULT_GDD_ROUNDS = 4
DEFAULT_GDD_OPTIONS = 3
_UNSAFE_FEATURE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LEADING_DOTS = re.compile(r"^\.+")


@dataclass
class UiProfile:
    framework: str = ""
    binding: str = ""
    notes: str = ""


@dataclass
class ProjectProfile:
    code_roots: list[str] = field(default_factory=list)
    namespaces: list[str] = field(default_factory=list)
    asmdefs: list[str] = field(default_factory=list)
    ui: UiProfile = field(default_factory=UiProfile)
    architecture: str = ""
    style: str = ""
    protected_paths: list[str] = field(default_factory=list)


@dataclass
class DocSetting:
    enabled: bool
    path: str


@dataclass
class DocsConfig:
    dev_spec: DocSetting
    feature_doc: DocSetting


@dataclass
class UnityMcpConfig:
    enabled: bool = True
    server: str = DEFAULT_MCP_SERVER
    url: str = DEFAULT_MCP_URL
    command: str = ""
    args: list[str] = field(default_factory=list)


@dataclass
class KnowledgeConfig:
    enabled: bool = True
    root: str = DEFAULT_KNOWLEDGE_ROOT


@dataclass
class FrameworkConfig:
    """独游模式的框架基线设置。"""

    enabled: bool = True
    plan: str = DEFAULT_FRAMEWORK_PLAN
    doc: str = DEFAULT_FRAMEWORK_DOC
    paradigm: str = ""


@dataclass
class DesignConfig:
    """从灵感迭代策划案的设置。"""

    path: str = DEFAULT_GDD
    rounds: int = DEFAULT_GDD_ROUNDS
    options: int = DEFAULT_GDD_OPTIONS


@dataclass
class WorkflowConfig:
    mode: WorkflowMode
    model: str
    docs: DocsConfig
    project: ProjectProfile
    unity_mcp: UnityMcpConfig = field(default_factory=UnityMcpConfig)
    client_spec_path: str = DEFAULT_CLIENT_SPEC
    knowledge: KnowledgeConfig = field(default_factory=KnowledgeConfig)
    framework: FrameworkConfig = field(default_factory=FrameworkConfig)
    design: DesignConfig = field(default_factory=DesignConfig)


@dataclass
class RunOverrides:
    model: str | None = None
    dev_spec_path: str | None = None
    feature_doc_path: str | None = None
    no_dev_spec: bool = False
    no_feature_doc: bool = False
    no_framework: bool = False


@dataclass
class ResolvedRunConfig:
    feature: str
    model: str
    dev_spec_enabled: bool
    feature_doc_enabled: bool
    dev_spec_path: str
    feature_doc_path: str
    game: str = "feature"
    framework_enabled: bool = False
    framework_plan_path: str = ""
    framework_doc_path: str = ""


def workflow_file(project_root: str | os.PathLike[str]) -> Path:
    return Path(project_root) / ".bulings" / "workflow.yaml"


def feature_from_design(design_path: str) -> str:
    return Path(design_path).stem


def feature_token(feature: str) -> str:
    trimmed = feature.strip()
    if not trimmed:
        return "feature"
    safe = _LEADING_DOTS.sub("", _UNSAFE_FEATURE.sub("-", trimmed))
    return safe or "feature"


def game_token(project_root: str | os.PathLike[str]) -> str:
    """从工程目录名得到框架文档要用的游戏标识。"""
    name = os.path.basename(os.path.abspath(project_root))
    return feature_token(name)


def merge_config(raw: object) -> WorkflowConfig:
    root = _as_object(raw) or {}
    mode_raw = root.get("mode")
    if mode_raw is not None and mode_raw not in ("work", "indie"):
        raise ValueError(f"workflow.yaml 的 mode 只能是 work 或 indie，当前是 {mode_raw}")

    docs = _as_object(root.get("docs")) or {}
    dev_spec = _as_object(docs.get("devSpec")) or {}
    feature_doc = _as_object(docs.get("featureDoc")) or {}
    project = _as_object(root.get("project")) or {}
    unity = _as_object(root.get("unity")) or {}
    mcp = _as_object(unity.get("mcp")) or {}
    knowledge = _as_object(root.get("knowledge")) or {}
    client_split = _as_object(root.get("clientSplit")) or {}
    ui = _as_object(project.get("ui")) or {}
    indie = _as_object(root.get("indie")) or {}
    framework = _as_object(indie.get("framework")) or {}
    design = _as_object(indie.get("design")) or {}

    return WorkflowConfig(
        unity_mcp=UnityMcpConfig(
            enabled=_as_boolean(mcp.get("enabled"), True),
            server=_non_empty_string(mcp.get("server"), DEFAULT_MCP_SERVER),
            url=_as_string(mcp["url"]) if "url" in mcp else DEFAULT_MCP_URL,
            command=_as_string(mcp.get("command")),
            args=_as_string_array(mcp.get("args")),
        ),
        knowledge=KnowledgeConfig(
            enabled=_as_boolean(knowledge.get("enabled"), True),
            root=_non_empty_string(knowledge.get("root"), DEFAULT_KNOWLEDGE_ROOT),
        ),
        framework=FrameworkConfig(
            enabled=_as_boolean(framework.get("enabled"), True),
            plan=_non_empty_string(framework.get("plan"), DEFAULT_FRAMEWORK_PLAN),
            doc=_non_empty_string(framework.get("doc"), DEFAULT_FRAMEWORK_DOC),
            paradigm=_as_string(framework.get("paradigm")),
        ),
        design=DesignConfig(
            path=_non_empty_string(design.get("path"), DEFAULT_GDD),
            rounds=_as_int(design.get("rounds"), DEFAULT_GDD_ROUNDS, 1, 12),
            options=_as_int(design.get("options"), DEFAULT_GDD_OPTIONS, 2, 5),
        ),
        client_spec_path=_non_empty_string(client_split.get("path"), DEFAULT_CLIENT_SPEC),
        mode="indie" if mode_raw == "indie" else "work",
        model=_non_empty_string(root.get("model"), DEFAULT_MODEL),
        docs=DocsConfig(
            dev_spec=DocSetting(
                enabled=_as_boolean(dev_spec.get("enabled"), True),
                path=_non_empty_string(dev_spec.get("path"), DEFAULT_DEV_SPEC),
            ),
            feature_doc=DocSetting(
                enabled=_as_boolean(feature_doc.get("enabled"), True),
                path=_non_empty_string(feature_doc.get("path"), DEFAULT_FEATURE_DOC),
            ),
        ),
        project=ProjectProfile(
            code_roots=_as_string_array(project.get("codeRoots")),
            namespaces=_as_string_array(project.get("namespaces")),
            asmdefs=_as_string_array(project.get("asmdefs")),
            ui=UiProfile(
                framework=_as_string(ui.get("framework")),
                binding=_as_string(ui.get("binding")),
                notes=_as_string(ui.get("notes")),
            ),
            architecture=_as_string(project.get("architecture")),
            style=_as_string(project.get("style")),
            protected_paths=_as_string_array(project.get("protectedPaths")),
        ),
    )


def load_workflow_config(project_root: str | os.PathLike[str]) -> WorkflowConfig:
    file_path = workflow_file(project_root)
    try:
        text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return merge_config(None)

    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"无法解析 {file_path}: {error}") from error
    return merge_config(parsed)


def resolve_run_config(
    config: WorkflowConfig,
    project_root: str | os.PathLike[str],
    feature: str,
    overrides: RunOverrides,
) -> ResolvedRunConfig:
    token = feature_token(feature)
    game = game_token(project_root)
    override_model = overrides.model.strip() if overrides.model and overrides.model.strip() else ""
    dev_spec_pattern = config.docs.dev_spec.path if overrides.dev_spec_path is None else overrides.dev_spec_path
    feature_doc_pattern = (
        config.docs.feature_doc.path if overrides.feature_doc_path is None else overrides.feature_doc_path
    )
    return ResolvedRunConfig(
        feature=token,
        model=override_model or config.model,
        dev_spec_enabled=False if overrides.no_dev_spec else config.docs.dev_spec.enabled,
        feature_doc_enabled=False if overrides.no_feature_doc else config.docs.feature_doc.enabled,
        dev_spec_path=resolve_doc_path(dev_spec_pattern, token, project_root),
        feature_doc_path=resolve_doc_path(feature_doc_pattern, token, project_root),
        game=game,
        framework_enabled=config.framework.enabled and not overrides.no_framework,
        framework_plan_path=resolve_template(config.framework.plan, {"feature": token, "game": game}, project_root),
        framework_doc_path=resolve_template(config.framework.doc, {"feature": token, "game": game}, project_root),
    )


def knowledge_map_path(config: WorkflowConfig, project_root: str | os.PathLike[str]) -> str | None:
    """知识库启用且 MAP.md 已存在时返回相对工程的路径，否则 None。"""
    if not config.knowledge.enabled:
        return None
    root = config.knowledge.root.rstrip("/\\")
    absolute = resolve_doc_path(root + "/MAP.md", "", project_root)
    if not os.path.isfile(absolute):
        return None
    return to_project_path(project_root, absolute)


def resolve_doc_path(pattern: str, feature: str, project_root: str | os.PathLike[str]) -> str:
    return resolve_template(pattern, {"feature": feature}, project_root)


def resolve_template(pattern: str, tokens: Mapping[str, str], project_root: str | os.PathLike[str]) -> str:
    """按 ``{game}`` / ``{feature}`` 之类的占位符展开路径，相对路径按工程根解析。"""
    replaced = pattern
    for key, value in tokens.items():
        replaced = replaced.replace("{" + key + "}", value)
    if os.path.isabs(replaced):
        return os.path.normpath(replaced)
    return os.path.normpath(os.path.join(os.path.abspath(project_root), replaced))


def to_project_path(project_root: str | os.PathLike[str], absolute_path: str) -> str:
    root = os.path.abspath(project_root)
    try:
        relative = os.path.relpath(absolute_path, root)
    except ValueError:
        return absolute_path
    if relative == os.curdir:
        return "."
    if relative.startswith("..") or os.path.isabs(relative):
        return absolute_path
    return relative.replace("\\", "/")


def _as_object(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    return None


def _as_string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _non_empty_string(value: object, fallback: str) -> str:
    if isinstance(value, str) and value.strip() != "":
        return value
    return fallback


def _as_boolean(value: object, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _as_int(value: object, fallback: int, low: int, high: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        return fallback
    return min(max(value, low), high)


def _as_string_array(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
