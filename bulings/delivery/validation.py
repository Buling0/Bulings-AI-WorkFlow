from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from bulings.delivery.errors import DeliveryError
from bulings.delivery.frontmatter import split_frontmatter
from bulings.delivery.paths import MANAGED_DOCUMENTS, document_id, rel_path_for_document

_LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_ALIAS_PATTERN = re.compile(r"^-\s*别名[：:]\s*(.+)\s*$")


@dataclass(frozen=True)
class DocumentError:
    document_id: str
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, str]:
        data = {"documentId": self.document_id, "code": self.code, "message": self.message}
        if self.path is not None:
            data["path"] = self.path
        return data


def validate_delivery(archive_path: Path, feature_id: str) -> list[DocumentError]:
    errors: list[DocumentError] = []
    for rel, suffix, _stage in MANAGED_DOCUMENTS:
        path = archive_path / rel
        doc = document_id(feature_id, suffix)
        if not path.is_file():
            errors.append(DocumentError(doc, "MISSING_FILE", "缺少文件", rel.replace("\\", "/")))
            continue
        try:
            text = path.read_text(encoding="utf-8")
            _meta, body = split_frontmatter(text)
        except DeliveryError as error:
            errors.append(DocumentError(doc, error.code, error.message, rel.replace("\\", "/")))
            continue
        if suffix == "requirements.terminology":
            errors.extend(_validate_terminology(doc, body, rel))
        project_root = archive_path.parent.parent.parent
        if suffix == "requirements.overview" and "## 场景" in body:
            from bulings.delivery.requirements_flow import validate_requirements_structure

            for message in validate_requirements_structure(project_root, archive_path, body, for_approve=False):
                errors.append(DocumentError(doc, "INVALID_REQUIREMENTS", message, rel.replace("\\", "/")))
        if suffix == "investigation.overview" and "## 事实" in body:
            from bulings.delivery.design_flow import validate_investigation_structure

            for message in validate_investigation_structure(project_root, body):
                errors.append(DocumentError(doc, "INVALID_INVESTIGATION", message, rel.replace("\\", "/")))
        if suffix == "design.overview" and "## 变化" in body:
            from bulings.delivery.design_flow import validate_design_structure

            for message in validate_design_structure(project_root, archive_path, body):
                errors.append(DocumentError(doc, "INVALID_DESIGN", message, rel.replace("\\", "/")))
        errors.extend(_validate_relative_links(doc, body, path.parent, rel))
    return errors


def validate_dependency_graph(feature_id: str, doc_id: str, dependencies: list[str]) -> None:
    for dep in dependencies:
        if dep == doc_id:
            raise DeliveryError(code="INVALID_DEPENDENCY", message="文档不能依赖自身", exit_code=1)
        if rel_path_for_document(feature_id, dep) is None:
            raise DeliveryError(code="INVALID_DEPENDENCY", message=f"未知依赖: {dep}", exit_code=1)
        if not _dependency_allowed(feature_id, doc_id, dep):
            raise DeliveryError(code="INVALID_DEPENDENCY", message=f"不允许的依赖: {dep}", exit_code=1)


def _dependency_allowed(feature_id: str, doc_id: str, dep_id: str) -> bool:
    from bulings.delivery.paths import document_suffix, stage_for_document_id

    doc_stage = stage_for_document_id(feature_id, doc_id)
    dep_stage = stage_for_document_id(feature_id, dep_id)
    if doc_stage is None or dep_stage is None:
        return False
    if dep_stage < doc_stage:
        return True
    if dep_stage == doc_stage:
        doc_suffix = document_suffix(doc_id, feature_id)
        dep_suffix = document_suffix(dep_id, feature_id)
        return doc_suffix == "requirements.overview" and dep_suffix == "requirements.terminology"
    return False


def _validate_terminology(doc_id: str, body: str, rel: str) -> list[DocumentError]:
    errors: list[DocumentError] = []
    rel_posix = rel.replace("\\", "/")
    lines = body.splitlines()
    section: str | None = None
    seen_names: set[str] = set()
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            title = line[3:].strip()
            if title == "已确认术语":
                section = "confirmed"
            elif title == "候选术语":
                section = "candidate"
            else:
                errors.append(DocumentError(doc_id, "TERMINOLOGY_SECTION", f"未知二级标题: {title}", rel_posix))
                section = None
            index += 1
            continue
        if line.startswith("### "):
            if section is None:
                errors.append(DocumentError(doc_id, "TERMINOLOGY_SECTION", "术语必须位于二级章节下", rel_posix))
                index += 1
                continue
            term_name = line[4:].strip()
            if not term_name:
                errors.append(DocumentError(doc_id, "TERMINOLOGY_TERM", "术语标题不能为空", rel_posix))
                index += 1
                continue
            if term_name in seen_names:
                errors.append(DocumentError(doc_id, "DUPLICATE_TERM", f"重复术语: {term_name}", rel_posix))
            seen_names.add(term_name)
            index += 1
            status_value: str | None = None
            has_definition = False
            while index < len(lines) and not lines[index].startswith("#"):
                item = lines[index].strip()
                if item.startswith("- 状态") or item.startswith("- 状态:"):
                    parts = re.split(r"[：:]", item[2:].strip(), maxsplit=1)
                    if len(parts) == 2:
                        status_value = parts[1].strip()
                elif item.startswith("- 一句话定义") or item.startswith("- 一句话定义:"):
                    has_definition = True
                else:
                    alias_match = _ALIAS_PATTERN.match(lines[index])
                    if alias_match:
                        for alias in _split_aliases(alias_match.group(1)):
                            if alias in seen_names:
                                errors.append(
                                    DocumentError(doc_id, "DUPLICATE_TERM", f"重复术语别名: {alias}", rel_posix)
                                )
                            seen_names.add(alias)
                index += 1
            if status_value is None:
                errors.append(DocumentError(doc_id, "TERMINOLOGY_TERM", f"缺少状态: {term_name}", rel_posix))
            elif section == "confirmed" and status_value != "已确认":
                errors.append(
                    DocumentError(doc_id, "TERMINOLOGY_STATUS", f"{term_name} 的状态与章节不一致", rel_posix)
                )
            elif section == "candidate" and status_value != "候选":
                errors.append(
                    DocumentError(doc_id, "TERMINOLOGY_STATUS", f"{term_name} 的状态与章节不一致", rel_posix)
                )
            if not has_definition:
                errors.append(DocumentError(doc_id, "TERMINOLOGY_TERM", f"缺少一句话定义: {term_name}", rel_posix))
            continue
        index += 1
    return errors


def _split_aliases(raw: str) -> list[str]:
    parts = re.split(r"[、,，]", raw)
    return [item.strip() for item in parts if item.strip()]


def _validate_relative_links(doc_id: str, body: str, base_dir: Path, rel: str) -> list[DocumentError]:
    errors: list[DocumentError] = []
    rel_posix = rel.replace("\\", "/")
    for segment in _markdown_segments_outside_code(body):
        for match in _LINK_PATTERN.finditer(segment):
            target = match.group(1).strip()
            if not target or target.startswith("http://") or target.startswith("https://"):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part or path_part.startswith("/"):
                continue
            resolved = (base_dir / path_part).resolve()
            try:
                resolved.relative_to(base_dir.resolve())
            except ValueError:
                errors.append(DocumentError(doc_id, "INVALID_LINK", f"链接越界: {target}", rel_posix))
                continue
            if not resolved.is_file():
                errors.append(DocumentError(doc_id, "BROKEN_LINK", f"链接目标不存在: {target}", rel_posix))
    return errors


def _markdown_segments_outside_code(body: str) -> list[str]:
    parts = re.split(r"```", body)
    segments: list[str] = []
    for index, part in enumerate(parts):
        if index % 2 == 1:
            continue
        segments.append(_strip_inline_code(part))
    return segments


def _strip_inline_code(text: str) -> str:
    return re.sub(r"`[^`]*`", "", text)
