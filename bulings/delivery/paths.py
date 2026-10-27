from __future__ import annotations

from pathlib import Path

DELIVERIES_DIR = ".bulings/deliveries"

ARCHIVE_RELATIVE_PATHS: tuple[str, ...] = (
    "feature.json",
    "01-requirements/README.md",
    "01-requirements/terminology.md",
    "02-investigation/README.md",
    "03-design/README.md",
    "04-plan/README.md",
    "05-implementation/README.md",
    "06-validation/README.md",
)

MANAGED_MARKDOWN_PATHS: tuple[str, ...] = tuple(
    rel for rel in ARCHIVE_RELATIVE_PATHS if rel.endswith(".md")
)

# (relative path, document suffix id, stage number for dependency rules)
MANAGED_DOCUMENTS: tuple[tuple[str, str, int], ...] = (
    ("01-requirements/terminology.md", "requirements.terminology", 1),
    ("01-requirements/README.md", "requirements.overview", 1),
    ("02-investigation/README.md", "investigation.overview", 2),
    ("03-design/README.md", "design.overview", 3),
    ("04-plan/README.md", "plan.overview", 4),
    ("05-implementation/README.md", "implementation.overview", 5),
    ("06-validation/README.md", "validation.overview", 6),
)

STAGE_OVERVIEW_DOC_IDS: dict[str, str] = {
    "01-requirements": "requirements.overview",
    "01-requirements/terminology.md": "requirements.terminology",
    "02-investigation": "investigation.overview",
    "03-design": "design.overview",
    "04-plan": "plan.overview",
    "05-implementation": "implementation.overview",
    "06-validation": "validation.overview",
}

CONTENT_STATUSES = frozenset({"draft", "ready", "stale", "blocked"})


def deliveries_root(project_root: Path) -> Path:
    return project_root / ".bulings" / "deliveries"


def archive_dir(project_root: Path, feature_id: str) -> Path:
    return deliveries_root(project_root) / feature_id


def archive_rel_path(feature_id: str) -> str:
    return f"{DELIVERIES_DIR}/{feature_id}"


def document_id(feature_id: str, suffix: str) -> str:
    return f"{feature_id}.{suffix}"


def document_suffix(full_id: str, feature_id: str) -> str | None:
    prefix = f"{feature_id}."
    if full_id.startswith(prefix):
        return full_id[len(prefix) :]
    return None


def rel_path_for_document(feature_id: str, doc_id: str) -> str | None:
    suffix = document_suffix(doc_id, feature_id)
    if suffix is None:
        return None
    for rel, doc_suffix, _stage in MANAGED_DOCUMENTS:
        if doc_suffix == suffix:
            return rel
    return None


def stage_for_document_id(feature_id: str, doc_id: str) -> int | None:
    suffix = document_suffix(doc_id, feature_id)
    if suffix is None:
        return None
    for _rel, doc_suffix, stage in MANAGED_DOCUMENTS:
        if doc_suffix == suffix:
            return stage
    return None


def sort_document_ids(feature_id: str, doc_ids: list[str]) -> list[str]:
    order = {document_id(feature_id, suffix): (stage, index) for index, (_r, suffix, stage) in enumerate(MANAGED_DOCUMENTS)}
    return sorted(doc_ids, key=lambda item: (order.get(item, (99, 99)), item))
