from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WorkflowMode = str
DEFAULT_MODEL = "composer-2.5"
DEFAULT_DEV_SPEC = "Docs/AI/DevSpecs/{feature}.md"
DEFAULT_FEATURE_DOC = "Docs/AI/Features/{feature}.md"
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
class WorkflowConfig:
    mode: WorkflowMode
    model: str
    docs: DocsConfig
    project: ProjectProfile


@dataclass
class RunOverrides:
    model: str | None = None
    dev_spec_path: str | None = None
    feature_doc_path: str | None = None
    no_dev_spec: bool = False
    no_feature_doc: bool = False


@dataclass
class ResolvedRunConfig:
    feature: str
    model: str
    dev_spec_enabled: bool
    feature_doc_enabled: bool
    dev_spec_path: str
    feature_doc_path: str


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


def merge_config(raw: object) -> WorkflowConfig:
    root = _as_object(raw) or {}
    mode_raw = root.get("mode")
    if mode_raw is not None and mode_raw not in ("work", "indie"):
        raise ValueError(f"workflow.yaml 的 mode 只能是 work 或 indie，当前是 {mode_raw}")

    docs = _as_object(root.get("docs")) or {}
    dev_spec = _as_object(docs.get("devSpec")) or {}
    feature_doc = _as_object(docs.get("featureDoc")) or {}
    project = _as_object(root.get("project")) or {}
    ui = _as_object(project.get("ui")) or {}

    return WorkflowConfig(
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
    )


def resolve_doc_path(pattern: str, feature: str, project_root: str | os.PathLike[str]) -> str:
    replaced = pattern.replace("{feature}", feature)
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


def _as_string_array(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
