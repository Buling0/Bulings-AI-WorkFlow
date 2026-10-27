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

STAGE_OVERVIEW_DOC_IDS: dict[str, str] = {
    "01-requirements": "requirements.overview",
    "01-requirements/terminology.md": "requirements.terminology",
    "02-investigation": "investigation.overview",
    "03-design": "design.overview",
    "04-plan": "plan.overview",
    "05-implementation": "implementation.overview",
    "06-validation": "validation.overview",
}


def deliveries_root(project_root: Path) -> Path:
    return project_root / ".bulings" / "deliveries"


def archive_dir(project_root: Path, feature_id: str) -> Path:
    return deliveries_root(project_root) / feature_id


def archive_rel_path(feature_id: str) -> str:
    return f"{DELIVERIES_DIR}/{feature_id}"
