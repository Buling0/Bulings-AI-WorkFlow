from __future__ import annotations

import json
from pathlib import Path

from bulings.gdd import (
    DIMENSIONS,
    covered_dimensions,
    decided_ids,
    design_brief_path,
    design_dir,
    design_plan_path,
    dimension_title,
    find_options,
    gdd_summary,
    option_ids,
    option_lines,
    parse_decisions,
    parse_gdd_plan,
    pending_dimensions,
    plan_status_lines,
    plan_summary,
    read_gdd_plan,
    stage_title,
    validate_round,
)


def _dimension(summary: str = "", confirmed: bool = False) -> dict:
    return {"summary": summary, "confirmed": confirmed}


def _option(option_id: str = "G1", **overrides) -> dict:
    payload = {
        "id": option_id,
        "dimension": "gameplay",
        "label": "实时塔防",
        "detail": "边打边建",
        "tradeoff": "上手更难",
    }
    payload.update(overrides)
    return payload


def _plan(**overrides) -> dict:
    payload = {
        "slug": "tower-defense",
        "title": "塔防 + 建造",
        "round": 1,
        "stage": "core",
        "status": "iterating",
        "dimensions": {name: _dimension() for name in DIMENSIONS},
        "options": [_option("G1"), _option("G2")],
        "chosen": [],
    }
    payload.update(overrides)
    return payload


def test_parses_a_complete_plan() -> None:
    plan = parse_gdd_plan(_plan())
    assert plan is not None
    assert plan.slug == "tower-defense"
    assert plan.round == 1
    assert plan.stage == "core"
    assert option_ids(plan) == {"G1", "G2"}
    assert plan.dimensions["gameplay"].confirmed is False


def test_options_and_chosen_may_be_missing() -> None:
    payload = _plan()
    payload.pop("options")
    payload.pop("chosen")
    plan = parse_gdd_plan(payload)
    assert plan is not None
    assert plan.options == []
    assert plan.chosen == []


def test_rejects_broken_header_fields() -> None:
    for key in ("slug", "title"):
        payload = _plan()
        payload.pop(key)
        assert parse_gdd_plan(payload) is None, key
        assert parse_gdd_plan(_plan(**{key: "  "})) is None
    assert parse_gdd_plan(_plan(round=0)) is None
    assert parse_gdd_plan(_plan(round=True)) is None
    assert parse_gdd_plan(_plan(round=1.5)) is None
    assert parse_gdd_plan(_plan(stage="idea")) is None
    assert parse_gdd_plan(_plan(status="draft")) is None
    assert parse_gdd_plan([]) is None


def test_rejects_broken_dimensions() -> None:
    payload = _plan()
    payload["dimensions"].pop("style")
    assert parse_gdd_plan(payload) is None
    assert parse_gdd_plan(_plan(dimensions={"gameplay": _dimension()})) is None
    broken = {name: _dimension() for name in DIMENSIONS}
    broken["story"] = {"summary": 3, "confirmed": False}
    assert parse_gdd_plan(_plan(dimensions=broken)) is None
    wrong_flag = {name: _dimension() for name in DIMENSIONS}
    wrong_flag["flow"] = {"summary": "", "confirmed": "yes"}
    assert parse_gdd_plan(_plan(dimensions=wrong_flag)) is None


def test_rejects_broken_options() -> None:
    assert parse_gdd_plan(_plan(options=[_option(), _option()])) is None
    assert parse_gdd_plan(_plan(options=[_option(id="  ")])) is None
    assert parse_gdd_plan(_plan(options=[_option(label="")])) is None
    assert parse_gdd_plan(_plan(options=[_option(dimension="music")])) is None
    assert parse_gdd_plan(_plan(options=[_option(detail=1)])) is None
    assert parse_gdd_plan(_plan(options="G1")) is None


def test_rejects_broken_chosen() -> None:
    assert parse_gdd_plan(_plan(chosen=[{"round": 0, "ids": []}])) is None
    assert parse_gdd_plan(_plan(chosen=[{"round": 1, "ids": "G1"}])) is None
    assert parse_gdd_plan(_plan(chosen=[{"round": 1, "ids": [], "note": 5}])) is None
    assert parse_gdd_plan(_plan(chosen="G1")) is None


def test_read_plan_returns_none_for_missing_or_invalid_files(tmp_path: Path) -> None:
    assert read_gdd_plan(tmp_path / "nope.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert read_gdd_plan(broken) is None
    good = tmp_path / "design.json"
    good.write_text(json.dumps(_plan(), ensure_ascii=False), encoding="utf-8")
    assert read_gdd_plan(good) is not None


def test_find_options_splits_found_and_missing() -> None:
    plan = parse_gdd_plan(_plan())
    assert plan is not None
    found, missing = find_options(plan, ["G2", "S9"])
    assert [option.id for option in found] == ["G2"]
    assert missing == ["S9"]


def test_parse_decisions_handles_commas_and_duplicates() -> None:
    assert parse_decisions("G1,S2 风格3，G1") == ["G1", "S2", "风格3"]
    assert parse_decisions("  ") == []
    assert parse_decisions("G1；G2、G2") == ["G1", "G2"]


def test_decided_ids_flattens_history() -> None:
    plan = parse_gdd_plan(
        _plan(chosen=[{"round": 1, "ids": ["G1"]}, {"round": 2, "ids": ["S1", "S2"], "note": "x"}])
    )
    assert plan is not None
    assert decided_ids(plan) == ["G1", "S1", "S2"]


def test_first_round_must_be_round_one() -> None:
    plan = parse_gdd_plan(_plan(round=1))
    assert plan is not None
    assert validate_round(None, plan, []) == []
    two = parse_gdd_plan(_plan(round=2))
    assert two is not None
    assert any("第一轮" in item for item in validate_round(None, two, []))
    assert any("第一轮" in item for item in validate_round(None, plan, ["G1"]))


def test_round_must_advance_exactly_one() -> None:
    previous = parse_gdd_plan(_plan(round=1))
    current = parse_gdd_plan(_plan(round=2, options=[_option("G1"), _option("G2")]))
    assert previous is not None and current is not None
    assert validate_round(previous, current, []) == []

    stuck = parse_gdd_plan(_plan(round=1))
    assert stuck is not None
    assert any("应该写 round 2" in item for item in validate_round(previous, stuck, []))

    jumped = parse_gdd_plan(_plan(round=3))
    assert jumped is not None
    assert any("应该写 round 2" in item for item in validate_round(previous, jumped, []))


def test_decisions_must_be_recorded_in_chosen() -> None:
    previous = parse_gdd_plan(_plan(round=1))
    current = parse_gdd_plan(_plan(round=2, chosen=[{"round": 2, "ids": ["G1"]}]))
    assert previous is not None and current is not None
    assert validate_round(previous, current, ["G1"]) == []
    errors = validate_round(previous, current, ["G1", "G2"])
    assert any("没有写进 chosen" in item for item in errors)


def test_iterating_round_needs_at_least_two_options() -> None:
    previous = parse_gdd_plan(_plan(round=1))
    single = parse_gdd_plan(_plan(round=2, options=[_option("G1")]))
    empty = parse_gdd_plan(_plan(round=2, options=[]))
    assert previous is not None and single is not None and empty is not None
    assert any("至少要给 2 个选项" in item for item in validate_round(previous, single, []))
    assert any("至少要给 2 个选项" in item for item in validate_round(previous, empty, []))
    assert validate_round(previous, single, [], min_options=1) == []


def test_finished_round_must_not_offer_options() -> None:
    previous = parse_gdd_plan(_plan(round=1))
    done = parse_gdd_plan(_plan(round=2, stage="done", status="done", options=[]))
    assert previous is not None and done is not None
    assert validate_round(previous, done, []) == []
    done_with_options = parse_gdd_plan(_plan(round=2, stage="done", status="done"))
    assert done_with_options is not None
    assert any("不该再给新选项" in item for item in validate_round(previous, done_with_options, []))


def test_dimension_helpers_track_progress() -> None:
    payload = _plan()
    payload["dimensions"]["gameplay"] = _dimension("核心循环定了", True)
    plan = parse_gdd_plan(payload)
    assert plan is not None
    assert covered_dimensions(plan) == ["gameplay"]
    assert pending_dimensions(plan) == ["story", "style", "flow"]
    assert stage_title("polish") == "数值、范围与里程碑"
    assert dimension_title("story") == "剧情"


def test_summary_and_display_lines() -> None:
    plan = parse_gdd_plan(_plan(chosen=[{"round": 1, "ids": ["G1"]}]))
    assert plan is not None
    summary = plan_summary(plan)
    assert "第 1 轮" in summary
    assert "G1" in summary
    status = plan_status_lines(plan)
    assert any("维度：" in line for line in status)
    assert any("G1" in line and "实时塔防" in line for line in status)
    assert any("代价：上手更难" in line for line in option_lines(plan))
    assert "第一轮" in gdd_summary(None)


def test_design_paths_live_under_the_project(tmp_path: Path) -> None:
    assert design_dir(tmp_path, "td") == tmp_path / ".bulings" / "design" / "td"
    assert design_plan_path(tmp_path, "td") == tmp_path / ".bulings" / "design" / "td" / "design.json"
    assert design_brief_path(tmp_path, "td") == tmp_path / ".bulings" / "design" / "td" / "brief.md"
