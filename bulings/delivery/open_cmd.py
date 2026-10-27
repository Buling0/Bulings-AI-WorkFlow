from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bulings.delivery.archive import delivery_status, list_deliveries
from bulings.delivery.errors import DeliveryError
from bulings.install import is_unity_project


@dataclass(frozen=True)
class DeliveryCandidate:
    feature_id: str
    title: str


@dataclass(frozen=True)
class OpenUniqueResult:
    match: str
    payload: dict[str, object]


def open_delivery(project_root: Path, query: str) -> OpenUniqueResult:
    project_root = project_root.resolve()
    if not is_unity_project(project_root):
        raise DeliveryError(
            code="NOT_UNITY_PROJECT",
            message=f"不是 Unity 工程（需要 Assets 和 ProjectSettings 目录）: {project_root}",
            exit_code=1,
        )
    normalized = query.strip()
    if not normalized:
        raise DeliveryError(code="INVALID_QUERY", message="--query 不能为空", exit_code=2)

    kind, chosen, matched = _find_matches(project_root, normalized)
    if kind == "unique" and chosen is not None:
        return _status_payload(project_root, chosen.feature_id, match="unique")
    if kind == "multiple":
        raise DeliveryError(
            code="MULTIPLE_MATCHES",
            message="多个交付项匹配查询",
            exit_code=1,
            candidates=[{"featureId": item.feature_id, "title": item.title} for item in matched],
        )
    raise DeliveryError(code="NOT_FOUND", message="没有匹配的交付项", exit_code=1)


def _find_matches(
    project_root: Path, query: str
) -> tuple[str, DeliveryCandidate | None, list[DeliveryCandidate]]:
    deliveries, _invalid = list_deliveries(project_root)
    candidates = [DeliveryCandidate(feature_id=item.feature_id, title=item.title) for item in deliveries]

    by_feature_id = [item for item in candidates if item.feature_id == query]
    if len(by_feature_id) == 1:
        return "unique", by_feature_id[0], []

    matched: list[DeliveryCandidate] = []
    for item in candidates:
        if item.feature_id == query:
            continue
        if item.title == query or query.lower() in item.title.lower():
            matched.append(item)

    if len(matched) == 1:
        return "unique", matched[0], []
    if len(matched) > 1:
        return "multiple", None, matched
    return "none", None, []


def _status_payload(project_root: Path, feature_id: str, *, match: str) -> OpenUniqueResult:
    detail = delivery_status(project_root, feature_id)
    payload: dict[str, object] = {
        "featureId": detail.feature_id,
        "title": detail.title,
        "profile": detail.profile,
        "lifecycle": detail.lifecycle,
        "archive": detail.archive,
        "updatedAt": detail.updated_at,
        "documentErrors": detail.document_errors,
        "approvalState": detail.approval_state,
        "slicePlan": detail.slice_plan,
        "sliceEligibility": detail.slice_eligibility,
        "match": match,
    }
    return OpenUniqueResult(match=match, payload=payload)
