"""The parts of workflow run reporting that need no database."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from rainstone.report_query import RunReportQuery
from rainstone.reporting import (
    BREAKDOWN_RUN_LIMIT,
    _attribute_shared_jobs,
    _bucket_function,
    _environment,
    _execution_span,
    _fold,
    _group_by_workflow,
    _RunSet,
    _select_runs,
    _step_order,
    _whole_run_range,
)

PERIOD = {
    "from_time": datetime(2026, 9, 1, tzinfo=UTC), "to_time": datetime(2026, 10, 1, tzinfo=UTC),
}


def make_run(
    number: int, amount: str | None, *, key: str = "workflow", status: str = "completed",
    total: str | None = None, complete: bool = True, jobs: dict[int, str | None] | None = None,
) -> dict:
    """The fields the selection, attribution and grouping code reads."""
    run_id = uuid.UUID(int=number)
    value = Decimal(amount) if amount is not None else None
    whole = Decimal(total if total is not None else amount) if (total or amount) else None
    return {
        "id": str(run_id), "_id": run_id, "workflow_key": key, "workflow_name": key.title(),
        "run_status": status, "started_at": datetime(2026, 9, 2, tzinfo=UTC) + timedelta(minutes=number),
        "_amount": value, "amount": amount, "_run_total": whole,
        "run_total": None if whole is None else format(whole, "f"),
        "run_total_complete": complete, "unpriced_job_count": 0,
        "_amounts": {
            uuid.UUID(int=job): None if cost is None else Decimal(cost)
            for job, cost in (jobs or {}).items()
        },
        "duration_seconds": 60,
        "_search": f"run-{number} {key}", "_focus_hit": None, "_rows": [],
        "chart_amount": None, "shared_job_count": 0,
    }


def run_set(runs: list[dict]) -> _RunSet:
    return _RunSet(runs, [], {}, [], None, datetime(2026, 9, 29, tzinfo=UTC))


class TestRunReportQuery:
    def test_defaults_to_a_page_of_twenty(self) -> None:
        assert RunReportQuery().limit == 20

    @pytest.mark.parametrize("limit", [0, 201])
    def test_limit_stays_within_two_hundred(self, limit: int) -> None:
        with pytest.raises(ValidationError):
            RunReportQuery(limit=limit)

    def test_focus_bounds_come_together(self) -> None:
        with pytest.raises(ValidationError, match="together"):
            RunReportQuery(focus_from=datetime(2026, 9, 2, tzinfo=UTC))

    def test_focus_bounds_are_ordered_and_offset_aware(self) -> None:
        start = datetime(2026, 9, 2, tzinfo=UTC)
        with pytest.raises(ValidationError, match="focus_from < focus_to"):
            RunReportQuery(focus_from=start, focus_to=start)
        with pytest.raises(ValidationError, match="UTC offset"):
            RunReportQuery(focus_from=datetime(2026, 9, 2), focus_to=datetime(2026, 9, 3))

    def test_focus_window_lies_inside_the_period(self) -> None:
        with pytest.raises(ValidationError, match="inside the period"):
            RunReportQuery(
                **PERIOD, focus_from=datetime(2026, 8, 31, 23, tzinfo=UTC),
                focus_to=datetime(2026, 9, 2, tzinfo=UTC),
            )
        with pytest.raises(ValidationError, match="inside the period"):
            RunReportQuery(
                **PERIOD, focus_from=datetime(2026, 9, 30, tzinfo=UTC),
                focus_to=datetime(2026, 10, 1, 1, tzinfo=UTC),
            )
        query = RunReportQuery(
            **PERIOD, focus_from=datetime(2026, 9, 30, tzinfo=UTC),
            focus_to=datetime(2026, 10, 1, tzinfo=UTC),
        )
        assert query.focus_to == PERIOD["to_time"]

    def test_a_grouped_selection_needs_both_bounds_and_a_workflow(self) -> None:
        boundary = str(uuid.uuid4())
        with pytest.raises(ValidationError, match="together"):
            RunReportQuery(workflow_key="w", max_run_amount=Decimal("1"))
        with pytest.raises(ValidationError, match="together"):
            RunReportQuery(workflow_key="w", boundary_run_id=boundary)
        with pytest.raises(ValidationError, match="workflow_key"):
            RunReportQuery(max_run_amount=Decimal("1"), boundary_run_id=boundary)

    def test_the_boundary_is_a_run_uuid_and_the_amount_nonnegative(self) -> None:
        with pytest.raises(ValidationError, match="UUID"):
            RunReportQuery(workflow_key="w", max_run_amount=Decimal("1"), boundary_run_id="nope")
        with pytest.raises(ValidationError, match="nonnegative"):
            RunReportQuery(
                workflow_key="w", max_run_amount=Decimal("-1"), boundary_run_id=str(uuid.uuid4())
            )

    def test_the_boundary_is_stored_in_canonical_form(self) -> None:
        run_id = uuid.uuid4()
        query = RunReportQuery(
            workflow_key="w", max_run_amount=Decimal("1"), boundary_run_id=run_id.hex.upper()
        )
        assert query.boundary_run_id == str(run_id)


class TestBucketBoundaries:
    def hours_in_local_day(self, timezone: str, year: int, month: int, day: int) -> int:
        zone = ZoneInfo(timezone)
        hour = _bucket_function("hour", zone)
        start, end = _bucket_function("day", zone)(datetime(year, month, day, 12, tzinfo=zone))
        count, cursor = 0, start
        while cursor < end:
            _, cursor = hour(cursor)
            count += 1
        return count

    def test_a_day_is_twenty_three_hours_when_clocks_spring_forward(self) -> None:
        assert self.hours_in_local_day("America/New_York", 2026, 3, 8) == 23

    def test_a_day_is_twenty_five_hours_when_clocks_fall_back(self) -> None:
        assert self.hours_in_local_day("America/New_York", 2026, 11, 1) == 25

    def test_an_ordinary_day_has_twenty_four_hourly_buckets(self) -> None:
        assert self.hours_in_local_day("America/New_York", 2026, 6, 10) == 24
        assert self.hours_in_local_day("UTC", 2026, 3, 8) == 24

    def test_day_buckets_start_at_local_midnight(self) -> None:
        zone = ZoneInfo("America/New_York")
        start, end = _bucket_function("day", zone)(datetime(2026, 9, 10, 3, 30, tzinfo=UTC))
        assert start == datetime(2026, 9, 9, 4, tzinfo=UTC)
        assert end == datetime(2026, 9, 10, 4, tzinfo=UTC)

    def test_weeks_start_on_monday(self) -> None:
        zone = ZoneInfo("UTC")
        # 2026-09-30 is a Wednesday.
        start, end = _bucket_function("week", zone)(datetime(2026, 9, 30, 15, tzinfo=UTC))
        assert start == datetime(2026, 9, 28, tzinfo=UTC)
        assert end == datetime(2026, 10, 5, tzinfo=UTC)

    def test_a_week_across_a_clock_change_keeps_local_midnights(self) -> None:
        zone = ZoneInfo("America/New_York")
        start, end = _bucket_function("week", zone)(datetime(2026, 3, 10, 12, tzinfo=UTC))
        assert start.astimezone(zone).isoformat() == "2026-03-09T00:00:00-04:00"
        assert end.astimezone(zone).isoformat() == "2026-03-16T00:00:00-04:00"

    def test_half_hour_zones_use_local_hours(self) -> None:
        zone = ZoneInfo("Asia/Kolkata")
        start, end = _bucket_function("hour", zone)(datetime(2026, 9, 10, 6, 40, tzinfo=UTC))
        assert start == datetime(2026, 9, 10, 6, 30, tzinfo=UTC)
        assert end - start == timedelta(hours=1)


class TestRemainderFolding:
    def test_a_fold_counts_failed_and_running_runs(self) -> None:
        runs = [
            make_run(1, "1", status="failed"), make_run(2, "2", status="running"),
            make_run(3, "3"),
        ]
        folded = _fold(runs, [Decimal("1"), Decimal("2"), Decimal("3")])
        assert folded == {"count": 3, "amount": "6", "failed": 1, "running": 1}

    def test_an_empty_fold_is_a_real_zero_with_no_boundary_yet(self) -> None:
        assert _fold([], []) == {"count": 0, "amount": "0", "failed": 0, "running": 0}

    def test_runs_beyond_the_cap_fold_into_a_remainder_with_an_exact_boundary(self) -> None:
        total = BREAKDOWN_RUN_LIMIT + 50
        runs = [make_run(n, "0.10", jobs={n: "0.10"}) for n in range(1, total + 1)]
        _attribute_shared_jobs(runs)
        [group] = _group_by_workflow(runs)
        assert len(group["runs"]) == BREAKDOWN_RUN_LIMIT
        assert group["run_count"] == total
        remainder = group["remainder"]
        assert remainder["count"] == 50
        assert Decimal(remainder["amount"]) == Decimal("5.00")
        # Equal amounts straddle the cap, so the boundary is settled by run ID.
        assert remainder["boundary"] == {
            "amount": "0.10", "run_id": str(uuid.UUID(int=BREAKDOWN_RUN_LIMIT + 1)),
        }
        assert [item["id"] for item in group["runs"]][-1] == str(uuid.UUID(int=BREAKDOWN_RUN_LIMIT))

    def test_the_boundary_selects_exactly_the_folded_runs(self) -> None:
        total = BREAKDOWN_RUN_LIMIT + 50
        runs = [make_run(n, "0.10", jobs={n: "0.10"}) for n in range(1, total + 1)]
        _attribute_shared_jobs(runs)
        [group] = _group_by_workflow(runs)
        boundary = group["remainder"]["boundary"]
        query = RunReportQuery(
            workflow_key="workflow", max_run_amount=Decimal(boundary["amount"]),
            boundary_run_id=boundary["run_id"],
        )
        selected = {run["id"] for run in _select_runs(run_set(runs), query)}
        shown = {item["id"] for item in group["runs"]}
        assert selected == {run["id"] for run in runs} - shown
        assert len(selected) == 50

    def test_amounts_that_round_to_the_same_cents_stay_distinct(self) -> None:
        amounts = ["1.004", "1.0041", "1.0049", "1.001", "0.999"]
        runs = [make_run(n + 1, amount, jobs={n + 1: amount}) for n, amount in enumerate(amounts)]
        _attribute_shared_jobs(runs)
        ordered = sorted(runs, key=lambda run: (-run["_amount"], run["_id"]))
        boundary = ordered[2]
        query = RunReportQuery(
            workflow_key="workflow", max_run_amount=boundary["_amount"],
            boundary_run_id=boundary["id"],
        )
        selected = _select_runs(run_set(runs), query)
        assert {run["id"] for run in selected} == {run["id"] for run in ordered[2:]}

    def test_unknown_amounts_are_never_part_of_a_grouped_selection(self) -> None:
        runs = [make_run(1, "0.10"), make_run(2, None), make_run(3, "0.05")]
        query = RunReportQuery(
            workflow_key="workflow", max_run_amount=Decimal("0.10"), boundary_run_id=runs[0]["id"]
        )
        assert {run["id"] for run in _select_runs(run_set(runs), query)} == {
            runs[0]["id"], runs[2]["id"],
        }


class TestSelection:
    def runs(self) -> list[dict]:
        return [
            make_run(1, "5", key="alpha", status="completed"),
            make_run(2, "3", key="alpha", status="failed"),
            make_run(3, "2", key="beta", status="completed"),
        ]

    def test_filters_narrow_the_runs_together(self) -> None:
        query = RunReportQuery(workflow_key="alpha", run_status="failed")
        assert [run["id"] for run in _select_runs(run_set(self.runs()), query)] == [
            str(uuid.UUID(int=2)),
        ]

    def test_search_matches_the_run_identity_ignoring_case(self) -> None:
        query = RunReportQuery(search="BETA")
        assert [run["_id"].int for run in _select_runs(run_set(self.runs()), query)] == [3]

    def test_setting_one_control_aside_leaves_the_rest_applied(self) -> None:
        query = RunReportQuery(workflow_key="alpha", run_status="failed")
        aside = _select_runs(run_set(self.runs()), query, ignoring="run_status")
        assert {run["_id"].int for run in aside} == {1, 2}
        aside = _select_runs(run_set(self.runs()), query, ignoring="workflow_key")
        assert {run["_id"].int for run in aside} == {2}

    def test_grouped_bounds_are_set_aside_with_the_control_that_made_them(self) -> None:
        runs = self.runs()
        query = RunReportQuery(
            workflow_key="alpha", max_run_amount=Decimal("3"), boundary_run_id=runs[1]["id"]
        )
        assert {run["_id"].int for run in _select_runs(run_set(runs), query)} == {2}
        aside = _select_runs(run_set(runs), query, ignoring="run_status")
        assert {run["_id"].int for run in aside} == {1, 2}


class TestAttribution:
    def test_a_shared_job_is_drawn_under_the_lowest_uuid(self) -> None:
        # A has 10 of its own work, B has 3, and they share one job worth 5.
        first = make_run(1, "15", jobs={101: "10", 900: "5"})
        second = make_run(2, "8", jobs={102: "3", 900: "5"})
        assigned, sharing = _attribute_shared_jobs([second, first])
        assert first["_chart_amount"] == Decimal("15")
        assert second["_chart_amount"] == Decimal("3")
        assert assigned[uuid.UUID(int=900)] == first["_id"]
        assert sharing[uuid.UUID(int=900)] == 2
        assert first["shared_job_count"] == second["shared_job_count"] == 1
        # Each run keeps counting every job it contains.
        assert first["_amount"] == Decimal("15") and second["_amount"] == Decimal("8")

    def test_a_run_alone_keeps_its_whole_amount(self) -> None:
        second = make_run(2, "8", jobs={102: "3", 900: "5"})
        _attribute_shared_jobs([second])
        assert second["_chart_amount"] == Decimal("8")
        assert second["shared_job_count"] == 0

    def test_the_assignment_does_not_depend_on_order(self) -> None:
        runs = [make_run(n, "5", jobs={900: "5", n: "0"}) for n in (3, 1, 2)]
        assigned, _ = _attribute_shared_jobs(runs)
        assert assigned[uuid.UUID(int=900)] == uuid.UUID(int=1)

    def test_unknown_work_adds_nothing_to_a_chart_contribution(self) -> None:
        run = make_run(1, "4", jobs={101: "4", 102: None})
        _attribute_shared_jobs([run])
        assert run["_chart_amount"] == Decimal("4")

    def test_a_run_with_no_known_cost_has_no_contribution_rather_than_zero(self) -> None:
        run = make_run(1, None, jobs={101: None})
        _attribute_shared_jobs([run])
        assert run["_chart_amount"] is None and run["chart_amount"] is None

    def test_a_run_whose_jobs_all_belong_elsewhere_contributes_a_known_zero(self) -> None:
        first = make_run(1, "5", jobs={900: "5"})
        second = make_run(2, "5", jobs={900: "5"})
        _attribute_shared_jobs([first, second])
        assert second["_chart_amount"] == Decimal("0")


class TestWholeRunRange:
    def test_the_range_uses_finished_complete_runs_and_counts_the_rest(self) -> None:
        runs = [
            make_run(1, "1", total="1.51"), make_run(2, "1", total="0.05"),
            make_run(3, "1", total="9", status="running"),
            make_run(4, "1", total="7", complete=False),
            make_run(5, None, total=None),
        ]
        assert _whole_run_range(runs) == {
            "minimum": "0.05", "maximum": "1.51", "included_run_count": 2,
            "excluded_run_count": 3,
        }

    def test_a_single_eligible_run_gives_equal_extrema(self) -> None:
        single = _whole_run_range([make_run(1, "2", total="2"), make_run(2, "1", status="running")])
        assert single["minimum"] == single["maximum"] == "2"
        assert single["included_run_count"] == 1

    def test_no_eligible_run_leaves_both_extrema_null(self) -> None:
        empty = _whole_run_range([make_run(1, "1", status="running")])
        assert empty == {
            "minimum": None, "maximum": None, "included_run_count": 0, "excluded_run_count": 1,
        }

    def test_a_known_zero_total_is_a_real_minimum(self) -> None:
        zero = _whole_run_range([make_run(1, "0", total="0"), make_run(2, "1", total="1")])
        assert zero["minimum"] == "0" and zero["maximum"] == "1"


class TestGroups:
    def test_groups_rank_by_attributed_amount_then_name_then_key(self) -> None:
        runs = [
            make_run(1, "1", key="b"), make_run(2, "1", key="a"), make_run(3, "9", key="c"),
            make_run(4, None, key="z"),
        ]
        for run in runs:
            run["_amounts"] = {run["_id"]: run["_amount"]}
        _attribute_shared_jobs(runs)
        assert [group["key"] for group in _group_by_workflow(runs)] == ["c", "a", "b", "z"]

    def test_a_group_of_unknown_cost_is_null_not_zero(self) -> None:
        run = make_run(1, None, jobs={1: None})
        _attribute_shared_jobs([run])
        [group] = _group_by_workflow([run])
        assert group["amount"] is None
        assert group["runs"] == []
        assert group["run_count"] == 1

    def test_runs_within_a_group_sort_by_amount_then_uuid(self) -> None:
        runs = [make_run(3, "1"), make_run(1, "1"), make_run(2, "2")]
        for run in runs:
            run["_amounts"] = {run["_id"]: run["_amount"]}
        _attribute_shared_jobs(runs)
        [group] = _group_by_workflow(runs)
        assert [uuid.UUID(item["id"]).int for item in group["runs"]] == [2, 1, 3]


AS_OF = datetime(2026, 9, 29, 12, tzinfo=UTC)


def make_attempt(number: int, start: str | None, finish: str | None, *, task: int = 0, ordinal: int = 1):
    def instant(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None

    return SimpleNamespace(
        id=uuid.UUID(int=number), source_attempt_id=f"provider-{number}", task_index=task,
        attempt_ordinal=ordinal, tool_started_at=instant(start), tool_finished_at=instant(finish),
    )


def span(state: str, *attempts) -> dict:
    return _execution_span({"state": state, "attempts": list(attempts)}, set(), AS_OF)


class TestStepOrder:
    def test_numeric_keys_compare_as_numbers(self) -> None:
        keys = ["10:40", "2:5", "2:11", "9:1"]
        assert sorted(keys, key=_step_order) == ["2:5", "2:11", "9:1", "10:40"]

    def test_a_key_that_is_not_numeric_sorts_after_those_that_are(self) -> None:
        assert sorted(["align", "3:1"], key=_step_order) == ["3:1", "align"]


class TestEnvironment:
    def test_one_capacity_is_the_environment(self) -> None:
        assert _environment(["dedicated"]) == "dedicated"

    def test_no_capacity_is_not_established(self) -> None:
        assert _environment([]) == "unknown"

    def test_several_capacities_are_named_as_several(self) -> None:
        assert _environment(["dedicated", "existing"]) == "multiple"


class TestExecutionSpan:
    def test_a_finished_job_runs_from_its_start_to_its_finish(self) -> None:
        result = span("ok", make_attempt(1, "2026-09-02T10:00:00", "2026-09-02T10:38:12"))
        assert result["duration_seconds"] == 38 * 60 + 12
        assert result["duration_running"] is False
        assert result["finished_at"] is not None

    def test_overlapping_attempts_are_not_added_twice(self) -> None:
        result = span(
            "ok",
            make_attempt(1, "2026-09-02T10:00:00", "2026-09-02T10:10:00", task=0),
            make_attempt(2, "2026-09-02T10:05:00", "2026-09-02T10:15:00", task=1),
        )
        assert result["duration_seconds"] == 15 * 60

    def test_the_wait_between_attempts_is_not_run_time(self) -> None:
        result = span(
            "ok",
            make_attempt(1, "2026-09-02T10:00:00", "2026-09-02T10:01:00", ordinal=1),
            make_attempt(2, "2026-09-02T11:00:00", "2026-09-02T11:02:00", ordinal=2),
        )
        assert result["duration_seconds"] == 3 * 60

    def test_a_running_job_is_timed_up_to_the_snapshot(self) -> None:
        result = span("running", make_attempt(1, "2026-09-29T11:00:00", None))
        assert result["duration_seconds"] == 3600
        assert result["duration_running"] is True
        assert result["finished_at"] is None

    def test_a_job_that_never_started_has_no_duration(self) -> None:
        assert span("queued", make_attempt(1, None, None))["duration_seconds"] is None
        assert span("new")["duration_seconds"] is None
        assert span("paused", make_attempt(1, "2026-09-02T10:00:00", None))["duration_seconds"] is None

    def test_a_finished_job_whose_end_was_never_recorded_has_no_duration(self) -> None:
        assert span("ok", make_attempt(1, "2026-09-02T10:00:00", None))["duration_seconds"] is None
