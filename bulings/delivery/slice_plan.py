from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from bulings.delivery.archive import archive_dir
from bulings.delivery.design_flow import DESIGN_REL, design_ready
from bulings.delivery.documents import assert_fresh, read_managed_document
from bulings.delivery.errors import Blocker, DeliveryError
from bulings.delivery.feature_id import is_valid_feature_id
from bulings.delivery.feature_json import read_feature_meta
from bulings.delivery.frontmatter import render_frontmatter
from bulings.delivery.paths import document_id
from bulings.delivery.requirements_flow import REQUIREMENTS_REL, list_requirement_scene_names
from bulings.delivery.time_util import format_iso8601
from bulings.delivery.fingerprint import content_fingerprint
from bulings.install import is_unity_project

NowFn = Callable[[], datetime]

PLAN_REL = "04-plan/README.md"
SLICE_PLAN_REL = "04-plan/slice-plan.json"
SLICE_PLAN_APPROVED_REL = "04-plan/slice-plan.approved.json"
HISTORY_DIR = "04-plan/history"


@dataclass(frozen=True)
class CheckSlicePlanResult:
    status: str
    slices: list[dict[str, Any]]
    digest: str


def prepare_plan(project_root: Path, feature_id: str, *, now: NowFn | None = None) -> str:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    project_root, archive, feature_meta = _load_context(project_root, feature_id)
    design_ready(project_root, feature_id)

    design_id = document_id(feature_id, "design.overview")
    design_meta, _ = read_managed_document(archive / DESIGN_REL)
    plan_meta, plan_body = read_managed_document(archive / PLAN_REL)
    expected_deps = [design_id]
    expected_versions = {design_id: str(design_meta.get("semanticVersion", "0.1.0"))}
    current_deps = _string_list(plan_meta.get("dependencies"))
    current_versions = _string_dict(plan_meta.get("dependencyVersions"))
    if current_deps == expected_deps and current_versions == expected_versions:
        return "unchanged"

    new_meta = dict(plan_meta)
    new_meta["dependencies"] = expected_deps
    new_meta["dependencyVersions"] = expected_versions
    normalized_body = plan_body if plan_body.startswith("\n") else "\n" + plan_body
    _atomic_write_files(
        {
            archive / PLAN_REL: render_frontmatter(new_meta, normalized_body),
            archive / "feature.json": _feature_json_with_updated_at(feature_meta, now_fn),
        }
    )
    return "prepared"


def prepare_slice_plan(project_root: Path, feature_id: str) -> str:
    project_root, archive, _feature_meta = _load_context(project_root, feature_id)
    design_ready(project_root, feature_id)
    plan_path = archive / SLICE_PLAN_REL
    if plan_path.is_file():
        return "unchanged"
    payload = {"schema": 1, "featureId": feature_id, "version": 1, "slices": []}
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return "created"


def check_slice_plan(project_root: Path, feature_id: str) -> CheckSlicePlanResult:
    project_root, archive, _feature_meta = _load_context(project_root, feature_id)
    try:
        design_ready(project_root, feature_id)
    except DeliveryError as error:
        raise DeliveryError(
            code="DESIGN_NOT_READY",
            message=error.message,
            exit_code=1,
            blockers=error.blockers or [Blocker(code="DESIGN_NOT_READY", message=error.message)],
        ) from error

    plan_id = document_id(feature_id, "plan.overview")
    try:
        assert_fresh(project_root, feature_id, [plan_id])
    except DeliveryError as error:
        raise DeliveryError(
            code="DESIGN_NOT_READY",
            message="计划总览未通过新鲜度检查",
            exit_code=1,
            blockers=error.blockers,
        ) from error

    raw_plan = _read_slice_plan(archive / SLICE_PLAN_REL)
    blockers = _validate_slice_plan(project_root, archive, feature_id, raw_plan)
    if blockers:
        raise DeliveryError(code="INVALID_SLICE_PLAN", message="切片方案检查失败", exit_code=1, blockers=blockers)

    normalized = normalize_slice_plan(raw_plan)
    digest = plan_digest(normalized)
    return CheckSlicePlanResult(status="valid", slices=normalized["slices"], digest=digest)


def approve_slice_plan(
    project_root: Path,
    feature_id: str,
    digest: str,
    *,
    now: NowFn | None = None,
) -> str:
    from bulings.delivery.archive import default_now

    now_fn = now or default_now
    project_root, archive, _feature_meta = _load_context(project_root, feature_id)
    check = check_slice_plan(project_root, feature_id)
    if check.digest != digest.strip():
        raise DeliveryError(code="DIGEST_MISMATCH", message="摘要与当前方案不一致", exit_code=1)

    approved_path = archive / SLICE_PLAN_APPROVED_REL
    normalized = normalize_slice_plan(_read_slice_plan(archive / SLICE_PLAN_REL))
    version = int(normalized["version"])

    if approved_path.is_file():
        existing = json.loads(approved_path.read_text(encoding="utf-8"))
        if int(existing.get("version", 0)) == version and str(existing.get("digest")) == check.digest:
            return "unchanged"
        if int(existing.get("version", 0)) == version and str(existing.get("digest")) != check.digest:
            raise DeliveryError(code="DIGEST_MISMATCH", message="同版本摘要不同，请提升 version", exit_code=1)
        old_version = int(existing.get("version", 0))
        if version > old_version:
            history_dir = archive / HISTORY_DIR
            history_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(approved_path), str(history_dir / f"slice-plan-v{old_version}.json"))

    stamp = format_iso8601(now_fn())
    approved_payload = dict(normalized)
    approved_payload["digest"] = check.digest
    approved_payload["approvedAt"] = stamp
    approved_path.write_text(json.dumps(approved_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return "approved"


def read_slice_plan_status(archive: Path) -> dict[str, Any] | None:
    approved_path = archive / SLICE_PLAN_APPROVED_REL
    if not approved_path.is_file():
        return None
    data = json.loads(approved_path.read_text(encoding="utf-8"))
    slices = data.get("slices")
    if not isinstance(slices, list):
        return None
    ids = sorted(str(item.get("id")) for item in slices if isinstance(item, dict) and item.get("id"))
    return {
        "version": data.get("version"),
        "digest": data.get("digest"),
        "sliceIds": ids,
    }


def compute_slice_eligibility(
    approved_plan: dict[str, Any],
    slice_states: dict[str, str] | None = None,
) -> dict[str, str]:
    slices = approved_plan.get("slices")
    if not isinstance(slices, list):
        return {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in slices:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            by_id[item["id"]] = item
    states = slice_states or {}
    accepted = {sid for sid, st in states.items() if st == "accepted"}

    eligibility: dict[str, str] = {}
    for slice_id, item in by_id.items():
        state = states.get(slice_id, "pending")
        if state in {"released", "accepted", "active", "in_review", "changes_requested"}:
            eligibility[slice_id] = "waiting"
            continue
        waiting = False
        for dep in _string_list(item.get("dependsOn")):
            if dep in by_id and dep not in accepted:
                waiting = True
        for replaced in _string_list(item.get("replaces")):
            if replaced in by_id and replaced not in accepted:
                waiting = True
        eligibility[slice_id] = "waiting" if waiting else "ready"
    return eligibility


def normalize_slice_plan(raw: dict[str, Any]) -> dict[str, Any]:
    slices_out: list[dict[str, Any]] = []
    for item in raw.get("slices", []):
        if not isinstance(item, dict):
            continue
        slice_id = item.get("id")
        if not isinstance(slice_id, str):
            continue
        depends = sorted(dict.fromkeys(_string_list(item.get("dependsOn"))))
        replaces = sorted(dict.fromkeys(_string_list(item.get("replaces"))))
        slices_out.append(
            {
                "dependsOn": depends,
                "id": slice_id,
                "replaces": replaces,
                "title": str(item.get("title", "")),
            }
        )
    slices_out.sort(key=lambda entry: entry["id"])
    return {
        "featureId": raw.get("featureId"),
        "schema": raw.get("schema"),
        "slices": slices_out,
        "version": raw.get("version"),
    }


def plan_digest(normalized: dict[str, Any]) -> str:
    payload = {
        "featureId": normalized["featureId"],
        "schema": normalized["schema"],
        "slices": normalized["slices"],
        "version": normalized["version"],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return content_fingerprint(text)


def parse_plan_slice_ids(plan_body: str) -> list[str]:
    entries = _parse_plan_entries(plan_body)
    return [entry.slice_id for entry in entries]


def _validate_slice_plan(
    project_root: Path,
    archive: Path,
    feature_id: str,
    raw: dict[str, Any],
) -> list[Blocker]:
    blockers: list[Blocker] = []
    if raw.get("schema") != 1:
        blockers.append(Blocker(code="INVALID_SLICE_PLAN", message="schema 必须为 1"))
    if raw.get("featureId") != feature_id:
        blockers.append(Blocker(code="INVALID_SLICE_PLAN", message="featureId 不一致"))
    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        blockers.append(Blocker(code="INVALID_SLICE_PLAN", message="version 必须是正整数"))

    slices = raw.get("slices")
    if not isinstance(slices, list) or len(slices) == 0:
        blockers.append(Blocker(code="INVALID_SLICE_PLAN", message="至少需要一个切片"))
        return blockers

    ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for item in slices:
        if not isinstance(item, dict):
            blockers.append(Blocker(code="INVALID_SLICE_PLAN", message="切片项必须是对象"))
            continue
        slice_id = item.get("id")
        if not isinstance(slice_id, str) or not is_valid_feature_id(slice_id):
            blockers.append(Blocker(code="INVALID_SLICE_PLAN", message=f"非法切片 id: {slice_id}"))
            continue
        if slice_id in by_id:
            blockers.append(Blocker(code="INVALID_SLICE_PLAN", message=f"重复切片 id: {slice_id}"))
        ids.append(slice_id)
        by_id[slice_id] = item

    for slice_id, item in by_id.items():
        for dep in _string_list(item.get("dependsOn")):
            if dep not in by_id:
                blockers.append(Blocker(code="UNKNOWN_SLICE", message=f"未知前置: {dep}", path=slice_id))
        for rep in _string_list(item.get("replaces")):
            if rep not in by_id:
                blockers.append(Blocker(code="UNKNOWN_SLICE", message=f"未知替代: {rep}", path=slice_id))

    if _has_cycle(by_id, "dependsOn"):
        blockers.append(Blocker(code="SLICE_CYCLE", message="dependsOn 存在环"))
    if _has_cycle(by_id, "replaces"):
        blockers.append(Blocker(code="SLICE_CYCLE", message="replaces 存在环"))

    for slice_id, item in by_id.items():
        forbidden = _replace_chain(by_id, _string_list(item.get("replaces")))
        forbidden.add(slice_id)
        deps_closure = _depends_closure(by_id, slice_id)
        overlap = deps_closure.intersection(forbidden)
        if overlap:
            blockers.append(
                Blocker(
                    code="SLICE_CYCLE",
                    message=f"依赖与替代冲突: {sorted(overlap)}",
                    path=slice_id,
                )
            )

    plan_body = read_managed_document(archive / PLAN_REL)[1]
    plan_ids = parse_plan_slice_ids(plan_body)
    if sorted(plan_ids) != sorted(ids):
        blockers.append(Blocker(code="PLAN_MISMATCH", message="计划总览与方案切片集合不一致"))

    req_scenes = set(list_requirement_scene_names(read_managed_document(archive / REQUIREMENTS_REL)[1]))
    covered = {entry.scene for entry in _parse_plan_entries(plan_body)}
    missing_scenes = req_scenes - covered
    if missing_scenes:
        blockers.append(Blocker(code="PLAN_MISMATCH", message=f"未覆盖场景: {sorted(missing_scenes)}"))
    return blockers


@dataclass
class _PlanEntry:
    slice_id: str
    scene: str


def _parse_plan_entries(plan_body: str) -> list[_PlanEntry]:
    lines = plan_body.splitlines()
    entries: list[_PlanEntry] = []
    block: list[str] = []
    in_split = False
    for line in lines:
        if line.strip() == "## 拆分":
            in_split = True
            continue
        if line.startswith("## ") and in_split:
            break
        if not in_split:
            continue
        if line.strip().startswith("- 结果"):
            if block:
                entry = _entry_from_block(block)
                if entry:
                    entries.append(entry)
            block = [line]
        elif block:
            block.append(line)
    if block:
        entry = _entry_from_block(block)
        if entry:
            entries.append(entry)
    return entries


def _entry_from_block(block: list[str]) -> _PlanEntry | None:
    slice_id: str | None = None
    scene: str | None = None
    for line in block:
        stripped = line.strip()
        if stripped.startswith("切片：") or stripped.startswith("切片:"):
            parts = re.split(r"[：:]", stripped, maxsplit=1)
            if len(parts) == 2:
                slice_id = parts[1].strip()
        if stripped.startswith("场景：") or stripped.startswith("场景:"):
            parts = re.split(r"[：:]", stripped, maxsplit=1)
            if len(parts) == 2:
                scene = parts[1].strip()
    if slice_id and scene:
        return _PlanEntry(slice_id=slice_id, scene=scene)
    return None


def _depends_closure(by_id: dict[str, dict[str, Any]], start: str) -> set[str]:
    seen: set[str] = set()
    stack = list(_string_list(by_id[start].get("dependsOn")))
    while stack:
        node = stack.pop()
        if node in seen or node not in by_id:
            continue
        seen.add(node)
        stack.extend(_string_list(by_id[node].get("dependsOn")))
    return seen


def _replace_chain(by_id: dict[str, dict[str, Any]], seeds: list[str]) -> set[str]:
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        node = stack.pop()
        if node in seen or node not in by_id:
            continue
        seen.add(node)
        stack.extend(_string_list(by_id[node].get("replaces")))
    return seen


def _has_cycle(by_id: dict[str, dict[str, Any]], field: str) -> bool:
    visited: set[str] = set()
    stack: set[str] = set()

    def visit(node: str) -> bool:
        if node in stack:
            return True
        if node in visited or node not in by_id:
            return False
        visited.add(node)
        stack.add(node)
        for nxt in _string_list(by_id[node].get(field)):
            if visit(nxt):
                return True
        stack.remove(node)
        return False

    return any(visit(node) for node in by_id)


def _read_slice_plan(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DeliveryError(code="MISSING_SLICE_PLAN", message="缺少 slice-plan.json", exit_code=1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DeliveryError(code="INVALID_SLICE_PLAN", message="无法读取 slice-plan.json") from error
    if not isinstance(data, dict):
        raise DeliveryError(code="INVALID_SLICE_PLAN", message="slice-plan.json 必须是对象")
    return data


def _load_context(project_root: Path, feature_id: str) -> tuple[Path, Path, dict[str, Any]]:
    if not is_valid_feature_id(feature_id):
        raise DeliveryError(code="INVALID_FEATURE_ID", message="feature-id 不合法", exit_code=2)
    if not is_unity_project(project_root):
        raise DeliveryError(code="NOT_UNITY_PROJECT", message="不是 Unity 工程", exit_code=1)
    project_root = project_root.resolve()
    archive = archive_dir(project_root, feature_id)
    if not archive.is_dir():
        raise DeliveryError(code="NOT_FOUND", message=f"找不到交付项: {feature_id}")
    return project_root, archive, read_feature_meta(archive / "feature.json")


def _feature_json_with_updated_at(feature_meta: dict[str, object], now_fn: NowFn) -> str:
    meta = dict(feature_meta)
    meta["updatedAt"] = format_iso8601(now_fn())
    return json.dumps(meta, indent=2, ensure_ascii=False) + "\n"


def _atomic_write_files(writes: dict[Path, str]) -> None:
    temp_paths: dict[Path, Path] = {}
    try:
        for target, content in writes.items():
            temp_path = target.with_suffix(target.suffix + ".tmp")
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_text(content, encoding="utf-8", newline="\n")
            temp_paths[target] = temp_path
        for target, temp_path in temp_paths.items():
            os.replace(temp_path, target)
    except Exception:
        for temp_path in temp_paths.values():
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)
        raise


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {key: val for key, val in value.items() if isinstance(key, str) and isinstance(val, str)}
