"""The workflow run endpoints, against the generated demonstration runs."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import (
    CostRevision,
    ExecutionAttempt,
    Invocation,
    InvocationJob,
    Job,
    Owner,
    Tenant,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import RUNS_TENANT, headers, run_headers

PERIOD = {"from": "2026-08-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"}
# Nothing here compares amounts to the cent: chunked accruals divide, so a sum
# in a different order can differ far below any displayed digit.
TOLERANCE = Decimal("1e-9")


def call(client, path: str, user: str = "admin", admin: bool = True, period=True, **params):
    query = {**(PERIOD if period else {}), **{k: v for k, v in params.items() if v is not None}}
    response = client.get(f"/api/{path}", params=query, headers=run_headers(user, admin))
    assert response.status_code == 200, response.text
    return response.json()


def every_run(client, **params) -> list[dict]:
    runs, offset = [], 0
    while True:
        page = call(client, "invocations", limit=200, offset=offset, **params)
        runs += page["items"]
        offset += 200
        if offset >= page["total"]:
            return runs


def job_amounts(client, **params) -> dict[str, Decimal | None]:
    amounts, offset = {}, 0
    while True:
        page = call(client, "jobs", limit=200, offset=offset, **params)
        for item in page["items"]:
            amounts[item["id"]] = Decimal(item["amount"]) if item["amount"] is not None else None
        offset += 200
        if offset >= page["total"]:
            return amounts


def known(values) -> Decimal | None:
    present = [value for value in values if value is not None]
    return sum(present, Decimal(0)) if present else None


def demo_roots() -> dict[str, set[str]]:
    """Each root run's job IDs, read straight from the membership table."""
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
        roots = {
            str(run.id): set() for run in session.scalars(
                select(Invocation).where(
                    Invocation.tenant_id == tenant.id, Invocation.parent_id.is_(None)
                )
            )
        }
        for invocation_id, job_id in session.execute(
            select(InvocationJob.invocation_id, InvocationJob.job_id)
            .join(Invocation, InvocationJob.invocation_id == Invocation.id)
            .where(Invocation.tenant_id == tenant.id)
        ):
            if str(invocation_id) in roots:
                roots[str(invocation_id)].add(str(job_id))
    return roots


def unique_cost(client, run_ids, **params) -> Decimal | None:
    amounts = job_amounts(client, **params)
    roots = demo_roots()
    members = set().union(*(roots[run_id] for run_id in run_ids)) if run_ids else set()
    return known(amounts.get(job_id) for job_id in members)


def owners_of_runs() -> dict[str, str]:
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
        rows = session.execute(
            select(Invocation.id, Owner.source_id)
            .join(Owner, Invocation.owner_id == Owner.id)
            .where(Invocation.tenant_id == tenant.id)
        ).all()
    return {str(row.id): row.source_id for row in rows}


class TestPeriodTotal:
    def test_the_total_is_the_unique_job_cost_of_every_run_in_the_period(self, client) -> None:
        runs = every_run(client)
        listing = call(client, "invocations", limit=200)
        totals = listing["totals"]
        assert len(runs) > 50
        assert totals["run_count"] == listing["total"] == len(runs)
        assert Decimal(totals["amount"]) == unique_cost(client, [run["id"] for run in runs])

    def test_paging_never_changes_the_total(self, client) -> None:
        wide = call(client, "invocations", limit=200)["totals"]
        assert call(client, "invocations", limit=5)["totals"] == wide
        assert call(client, "invocations", limit=5, offset=100)["totals"] == wide
        assert call(client, "invocations", limit=1, offset=wide["run_count"] - 1)["totals"] == wide

    def test_every_run_is_reachable_by_offset(self, client) -> None:
        seen, offset = [], 0
        while True:
            page = call(client, "invocations", limit=50, offset=offset)
            assert page["limit"] == 50 and page["offset"] == offset
            seen += [item["id"] for item in page["items"]]
            offset += 50
            if offset >= page["total"]:
                break
        assert len(seen) == page["total"] > 50
        assert len(set(seen)) == len(seen)

    def test_the_default_page_is_twenty_and_sorted_newest_first(self, client) -> None:
        page = call(client, "invocations")
        assert page["limit"] == 20 and len(page["items"]) == 20
        started = [item["started_at"] for item in page["items"]]
        assert started == sorted(started, reverse=True)

    def test_outcome_counts_sum_to_the_run_count(self, client) -> None:
        totals = call(client, "invocations")["totals"]
        assert sum(totals["by_status"].values()) == totals["run_count"]
        assert totals["by_status"]["failed"] > 0
        assert totals["by_status"]["running"] == 3
        assert totals["workflow_count"] == 8

    def test_the_total_differs_from_overview_by_the_cost_of_jobs_outside_workflows(
        self, client
    ) -> None:
        totals = call(client, "invocations")["totals"]
        overview = call(client, "summary")
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            in_a_run = {
                str(job_id) for job_id in session.scalars(
                    select(InvocationJob.job_id).join(
                        Invocation, InvocationJob.invocation_id == Invocation.id
                    ).where(Invocation.tenant_id == tenant.id)
                )
            }
        amounts = job_amounts(client)
        outside = known(amount for job_id, amount in amounts.items() if job_id not in in_a_run)
        assert outside and outside > 0
        assert Decimal(overview["amount"]) == Decimal(totals["amount"]) + outside

    def test_overviews_top_runs_are_the_four_most_expensive_of_the_period(self, client) -> None:
        top = call(client, "invocations", run_sort="amount", direction="desc", limit=4)["items"]
        amounts = sorted(
            (Decimal(run["amount"]) for run in every_run(client) if run["amount"] is not None),
            reverse=True,
        )
        assert [Decimal(run["amount"]) for run in top] == amounts[:4]


class TestRunFacts:
    def test_a_run_reports_when_it_finished_and_how_long_it_took(self, client) -> None:
        runs = every_run(client)
        finished = [run for run in runs if run["run_status"] in {"completed", "failed"}]
        assert finished
        with Session(engine) as session:
            latest = defaultdict(lambda: None)
            for invocation_id, finish in session.execute(
                select(InvocationJob.invocation_id, ExecutionAttempt.tool_finished_at)
                .join(ExecutionAttempt, ExecutionAttempt.job_id == InvocationJob.job_id)
            ):
                if finish and (latest[str(invocation_id)] is None or finish > latest[str(invocation_id)]):
                    latest[str(invocation_id)] = finish
        for run in finished:
            assert run["finished_at"] is not None
            assert datetime.fromisoformat(run["finished_at"]) == latest[run["id"]]
            span = datetime.fromisoformat(run["finished_at"]) - datetime.fromisoformat(run["started_at"])
            assert run["duration_seconds"] == int(span.total_seconds())

    def test_a_running_run_has_no_finish_and_a_duration_to_the_revision(self, client) -> None:
        running = [run for run in every_run(client) if run["run_status"] == "running"]
        assert len(running) == 3
        as_of = datetime.fromisoformat(call(client, "invocations")["meta"]["as_of"])
        for run in running:
            assert run["finished_at"] is None
            span = as_of - datetime.fromisoformat(run["started_at"])
            assert run["duration_seconds"] == int(span.total_seconds())

    def test_runs_of_one_stored_workflow_share_a_key_across_saved_versions(self, client) -> None:
        by_name = defaultdict(set)
        by_key = defaultdict(set)
        for run in every_run(client):
            by_name[run["workflow_name"]].add(run["workflow_key"])
            by_key[run["workflow_key"]].add(run["workflow_id"])
        assert all(len(keys) == 1 for keys in by_name.values())
        # Saved versions differ in workflow ID but land in one group.
        assert any(len(ids) > 1 for ids in by_key.values())

    def test_the_run_detail_carries_finish_and_duration(self, client) -> None:
        run = next(run for run in every_run(client) if run["run_status"] == "completed")
        detail = client.get(
            f"/api/invocations/{run['id']}", params=PERIOD, headers=run_headers()
        ).json()
        assert detail["finished_at"] == run["finished_at"]
        assert detail["duration_seconds"] == run["duration_seconds"]
        assert detail["steps"]

    def test_a_run_beyond_the_first_page_still_opens(self, client) -> None:
        oldest = call(client, "invocations", limit=1, direction="asc")["items"][0]
        response = client.get(
            f"/api/invocations/{oldest['id']}", params=PERIOD, headers=run_headers()
        )
        assert response.status_code == 200

    def test_a_nested_root_counts_its_child_jobs_once(self, client) -> None:
        runs = every_run(client)
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            child = session.scalar(
                select(Invocation)
                .where(Invocation.tenant_id == tenant.id, Invocation.parent_id.is_not(None))
                .limit(1)
            )
            root_id = str(child.parent_id)
            child_jobs = set(session.scalars(
                select(InvocationJob.job_id).where(InvocationJob.invocation_id == child.id)
            ))
        root = next(run for run in runs if run["id"] == root_id)
        assert child_jobs
        assert root["run_job_count"] >= len(child_jobs)
        assert root["run_job_count"] == len(demo_roots()[root_id])

    def test_sorting_puts_unknown_costs_last_in_both_directions(self, client) -> None:
        for direction in ("asc", "desc"):
            runs = call(client, "invocations", run_sort="amount", direction=direction, limit=200)[
                "items"
            ]
            amounts = [run["amount"] for run in runs]
            first_unknown = next((n for n, value in enumerate(amounts) if value is None), None)
            if first_unknown is not None:
                assert all(value is None for value in amounts[first_unknown:])
            values = [Decimal(value) for value in amounts if value is not None]
            assert values == sorted(values, reverse=direction == "desc")

    def test_longest_running_sorts_by_duration(self, client) -> None:
        runs = call(client, "invocations", run_sort="duration", direction="desc", limit=200)["items"]
        durations = [run["duration_seconds"] for run in runs if run["duration_seconds"] is not None]
        assert durations == sorted(durations, reverse=True)


def workflow_options(client, **params) -> list[dict]:
    return call(client, "invocations", limit=1, **params)["filter_options"]["workflows"]


def a_window() -> dict[str, str]:
    return {"focus_from": "2026-08-15T00:00:00Z", "focus_to": "2026-08-18T00:00:00Z"}


def filter_cases(client) -> list[dict]:
    workflows = workflow_options(client)
    busiest = max(workflows, key=lambda option: option["run_count"])
    return [
        {"run_status": "failed"},
        {"run_status": "completed", "workflow_key": busiest["key"]},
        {"workflow_key": busiest["key"]},
        {"search": "rna"},
        a_window(),
        {**a_window(), "run_status": "completed"},
        {**a_window(), "workflow_key": busiest["key"], "search": "variant"},
    ]


class TestUniformFiltering:
    def test_every_filter_narrows_every_endpoint_to_the_same_runs(self, client) -> None:
        for params in filter_cases(client):
            listing = every_run(client, **params)
            ids = {run["id"] for run in listing}
            totals = call(client, "invocations", limit=1, **params)["totals"]
            breakdown = call(client, "invocations/breakdown", **params)
            timeline = call(client, "invocations/timeline", bucket="day", **params)
            assert totals["run_count"] == len(ids), params
            assert sum(group["run_count"] for group in breakdown["groups"]) == len(ids), params
            drawn = {run["id"] for group in breakdown["groups"] for run in group["runs"]}
            assert drawn == {run["id"] for run in listing if run["amount"] is not None}, params
            pieces = {piece["id"] for bucket in timeline["buckets"] for piece in bucket["pieces"]}
            assert pieces <= ids, params

    def test_chart_contributions_equal_the_card_under_every_filter(self, client) -> None:
        for params in filter_cases(client) + [{}]:
            totals = call(client, "invocations", limit=1, **params)["totals"]
            breakdown = call(client, "invocations/breakdown", **params)
            timeline = call(client, "invocations/timeline", bucket="day", **params)
            expected = Decimal(totals["amount"]) if totals["amount"] is not None else None
            assert known(
                Decimal(group["amount"]) if group["amount"] is not None else None
                for group in breakdown["groups"]
            ) == expected, params
            drawn = known(
                Decimal(bucket["amount"]) if bucket["amount"] is not None else None
                for bucket in timeline["buckets"]
            )
            if expected is None:
                assert drawn is None, params
            else:
                assert abs(drawn - expected) < TOLERANCE, params

    def test_the_totals_equal_the_unique_job_cost_of_the_matching_runs(self, client) -> None:
        for params in filter_cases(client):
            listing = every_run(client, **params)
            totals = call(client, "invocations", limit=1, **params)["totals"]
            expected = unique_cost(client, [run["id"] for run in listing])
            assert (Decimal(totals["amount"]) if totals["amount"] else None) == expected, params

    def test_a_failed_filter_removes_the_completed_runs_and_keeps_the_choices(self, client) -> None:
        everything = call(client, "invocations", limit=1)
        failed = call(client, "invocations", limit=200, run_status="failed")
        assert {run["run_status"] for run in failed["items"]} == {"failed"}
        assert failed["totals"]["by_status"] == {"failed": failed["totals"]["run_count"]}
        assert failed["totals"]["unfiltered_run_count"] == everything["totals"]["run_count"]
        # The outcome choices still describe what selecting each would show.
        assert failed["filter_options"]["by_status"] == everything["filter_options"]["by_status"]

    def test_the_workflow_choices_ignore_only_the_workflow_choice(self, client) -> None:
        options = workflow_options(client)
        chosen = options[0]["key"]
        narrowed = call(client, "invocations", limit=1, workflow_key=chosen, run_status="failed")
        assert narrowed["filter_options"]["workflows"] == workflow_options(client, run_status="failed")
        assert len(narrowed["filter_options"]["workflows"]) > 1
        by_status = narrowed["filter_options"]["by_status"]
        assert by_status == call(client, "invocations", limit=1, workflow_key=chosen)[
            "filter_options"
        ]["by_status"]

    def test_the_workflow_choices_stay_available_on_the_time_tab_request(self, client) -> None:
        # The options come from /invocations alone; no chart endpoint supplies them.
        options = workflow_options(client)
        assert len(options) == 8
        assert all(option["run_count"] > 0 and option["name"] for option in options)

    def test_a_selected_option_with_no_matches_stays_so_it_can_be_cleared(self, client) -> None:
        options = workflow_options(client)
        smallest = min(options, key=lambda option: option["run_count"])
        result = call(client, "invocations", limit=1, workflow_key=smallest["key"], search="zzz-none")
        assert result["totals"]["run_count"] == 0
        assert {"key": smallest["key"], "name": smallest["name"], "run_count": 0} in result[
            "filter_options"
        ]["workflows"]
        result = call(client, "invocations", limit=1, run_status="cancelled", search="zzz-none")
        assert result["filter_options"]["by_status"]["cancelled"] == 0

    def test_a_focus_window_selects_runs_but_keeps_their_whole_period_share(self, client) -> None:
        everything = {run["id"]: run for run in every_run(client)}
        focused = every_run(client, **a_window())
        assert 0 < len(focused) < len(everything)
        for run in focused:
            assert run["amount"] == everything[run["id"]]["amount"]
            assert run["run_total"] == everything[run["id"]]["run_total"]
            started = datetime.fromisoformat(run["started_at"])
            assert started < datetime(2026, 8, 18, tzinfo=UTC)
            if run["finished_at"]:
                assert datetime.fromisoformat(run["finished_at"]) >= datetime(2026, 8, 15, tzinfo=UTC)

    def test_an_empty_window_selects_nothing(self, client) -> None:
        result = call(
            client, "invocations", focus_from="2026-07-01T00:00:00Z", focus_to="2026-07-02T00:00:00Z",
            period=False, **{"from": "2026-07-01T00:00:00Z", "to": "2026-07-03T00:00:00Z"},
        )
        assert result["items"] == [] and result["totals"]["run_count"] == 0

    def test_search_finds_runs_by_workflow_name(self, client) -> None:
        found = every_run(client, search="metagenomic")
        assert found and {run["workflow_name"] for run in found} == {"Metagenomic profiling"}


class TestGroupedSelection:
    def test_a_boundary_selects_exactly_the_runs_at_and_below_it(self, client) -> None:
        key = max(workflow_options(client), key=lambda option: option["run_count"])["key"]
        [group] = [
            g for g in call(client, "invocations/breakdown", workflow_key=key)["groups"]
            if g["key"] == key
        ]
        runs = group["runs"]
        assert len(runs) > 12
        for position in (0, 7, len(runs) - 1):
            boundary = runs[position]
            selected = every_run(
                client, workflow_key=key, max_run_amount=boundary["amount"],
                boundary_run_id=boundary["id"],
            )
            assert {run["id"] for run in selected} == {run["id"] for run in runs[position:]}

    def test_selection_survives_a_second_request_at_the_same_revision(self, client) -> None:
        key = workflow_options(client)[0]["key"]
        [group] = [
            g for g in call(client, "invocations/breakdown", workflow_key=key)["groups"]
            if g["key"] == key
        ]
        boundary = group["runs"][3]
        revision = call(client, "summary")["revision_id"]
        arguments = {
            "workflow_key": key, "max_run_amount": boundary["amount"],
            "boundary_run_id": boundary["id"], "revision": revision,
        }
        first = call(client, "invocations", limit=200, **arguments)
        second = call(client, "invocations/breakdown", **arguments)
        third = call(client, "invocations/timeline", bucket="day", **arguments)
        ids = {run["id"] for run in first["items"]}
        assert {run["id"] for g in second["groups"] for run in g["runs"]} <= ids
        assert {p["id"] for b in third["buckets"] for p in b["pieces"]} <= ids

    def test_the_grouped_bounds_are_ignored_by_the_sidebar_choices(self, client) -> None:
        key = workflow_options(client)[0]["key"]
        [group] = [
            g for g in call(client, "invocations/breakdown", workflow_key=key)["groups"]
            if g["key"] == key
        ]
        boundary = group["runs"][5]
        bounded = call(
            client, "invocations", limit=1, workflow_key=key,
            max_run_amount=boundary["amount"], boundary_run_id=boundary["id"],
        )
        plain = call(client, "invocations", limit=1, workflow_key=key)
        assert bounded["filter_options"] == plain["filter_options"]
        assert bounded["totals"]["run_count"] < plain["totals"]["run_count"]


class TestSharedJobs:
    def shared_jobs(self) -> dict[str, list[str]]:
        holders = defaultdict(list)
        for run_id, jobs in demo_roots().items():
            for job_id in jobs:
                holders[job_id].append(run_id)
        return {job: sorted(runs) for job, runs in holders.items() if len(runs) > 1}

    def test_the_demonstration_shares_jobs_between_runs(self, client) -> None:
        assert len(self.shared_jobs()) == 2

    def test_a_shared_job_is_counted_once_in_the_total_and_the_charts(self, client) -> None:
        listing = every_run(client)
        totals = call(client, "invocations", limit=1)["totals"]
        raw = known(Decimal(run["amount"]) if run["amount"] else None for run in listing)
        amounts = job_amounts(client)
        overlap = sum(
            (len(holders) - 1) * (amounts[job_id] or Decimal(0))
            for job_id, holders in self.shared_jobs().items()
        )
        assert totals["shared_job_count"] == 2
        assert overlap > 0
        assert raw - Decimal(totals["amount"]) == overlap
        contributions = known(
            Decimal(run["chart_amount"]) if run["chart_amount"] else None for run in listing
        )
        assert contributions == Decimal(totals["amount"])

    def test_the_lowest_uuid_takes_the_shared_job_in_every_chart(self, client) -> None:
        listing = {run["id"]: run for run in every_run(client)}
        breakdown = call(client, "invocations/breakdown")
        drawn = {run["id"]: run for g in breakdown["groups"] for run in g["runs"]}
        amounts = job_amounts(client)
        for job_id, holders in self.shared_jobs().items():
            taker, other = holders[0], holders[1]
            # The run that gave the job up still counts it in its own amount.
            gave_up = Decimal(listing[other]["amount"]) - Decimal(listing[other]["chart_amount"])
            assert gave_up == amounts[job_id]
            assert listing[taker]["chart_amount"] == listing[taker]["amount"]
            # Every chart draws the same contribution the list reports.
            assert drawn[other]["chart_amount"] == listing[other]["chart_amount"]
            assert drawn[taker]["chart_amount"] == listing[taker]["chart_amount"]
        assert all(listing[run_id]["amount"] == drawn[run_id]["amount"] for run_id in drawn)

    def test_raw_run_amounts_and_totals_are_unchanged_by_the_attribution(self, client) -> None:
        job_id, holders = next(iter(self.shared_jobs().items()))
        together = {run["id"]: run for run in every_run(client)}
        for run_id in holders:
            alone = call(client, "invocations", invocation_id=run_id)["items"][0]
            assert alone["amount"] == together[run_id]["amount"]
            assert alone["run_total"] == together[run_id]["run_total"]
            # Filtered to one run, it draws every job it contains.
            assert alone["chart_amount"] == alone["amount"]
            assert alone["shared_job_count"] == 0
        lowest, highest = holders[0], holders[-1]
        assert Decimal(together[highest]["chart_amount"]) <= Decimal(together[highest]["amount"])
        assert together[lowest]["chart_amount"] == together[lowest]["amount"]

    def test_filtering_one_sharing_run_out_gives_the_other_its_full_amount(self, client) -> None:
        job_id, holders = next(iter(self.shared_jobs().items()))
        remaining = holders[-1]
        totals = call(client, "invocations", invocation_id=remaining)["totals"]
        item = call(client, "invocations", invocation_id=remaining)["items"][0]
        assert totals["shared_job_count"] == 0
        assert totals["amount"] == item["amount"] == item["chart_amount"]


class TestCoverage:
    def test_runs_with_unpriced_jobs_say_so_and_never_read_as_zero(self, client) -> None:
        listing = every_run(client)
        incomplete = [run for run in listing if run["run_unpriced_job_count"]]
        assert len(incomplete) >= 4
        assert all(run["run_total_complete"] is False for run in incomplete)
        totals = call(client, "invocations", limit=1)["totals"]
        assert 0 < totals["incomplete_run_count"] <= len(incomplete)
        assert totals["amount"] is not None

    def test_the_whole_run_range_excludes_incomplete_and_running_runs_with_counts(
        self, client
    ) -> None:
        breakdown = call(client, "invocations/breakdown")
        listing = every_run(client)
        for group in breakdown["groups"]:
            members = [run for run in listing if run["workflow_key"] == group["key"]]
            eligible = [
                Decimal(run["run_total"]) for run in members
                if run["run_status"] != "running" and run["run_total_complete"]
                and run["run_total"] is not None
            ]
            found = group["whole_run_range"]
            assert found["included_run_count"] == len(eligible)
            assert found["excluded_run_count"] == len(members) - len(eligible)
            if eligible:
                assert Decimal(found["minimum"]) == min(eligible)
                assert Decimal(found["maximum"]) == max(eligible)
            else:
                assert found["minimum"] is None and found["maximum"] is None

    def test_an_empty_result_is_explicitly_empty(self, client) -> None:
        listing = call(client, "invocations", search="zzz-none")
        assert listing["items"] == [] and listing["total"] == 0
        totals = listing["totals"]
        assert totals["amount"] is None and totals["run_count"] == 0
        assert totals["by_status"] == {} and totals["workflow_count"] == 0
        assert call(client, "invocations/breakdown", search="zzz-none")["groups"] == []
        timeline = call(client, "invocations/timeline", search="zzz-none")
        assert timeline["buckets"] == [] and timeline["axis"] is None

    def test_known_zero_work_is_an_observed_zero(self, client) -> None:
        zero = [
            run for run in every_run(client)
            if run["workflow_name"] == "Quality control and trimming" and run["run_status"] == "completed"
        ]
        assert zero
        # Their first step ran on the existing server, so it adds no compute.
        assert all(run["amount"] is not None for run in zero)

    def test_a_workflow_group_of_only_unknown_cost_has_no_amount(self, client) -> None:
        # No demonstration workflow is entirely unknown, so a run with unknown cost is
        # searched alone; its group keeps the run in coverage counts without a block.
        unknown = [run for run in every_run(client) if run["amount"] is None]
        if not unknown:
            pytest.skip("every demonstration run has a known period share")
        run = unknown[0]
        groups = call(client, "invocations/breakdown", invocation_id=run["id"])["groups"]
        assert groups[0]["amount"] is None and groups[0]["runs"] == []
        assert groups[0]["run_count"] == 1


class TestTimeline:
    def test_day_buckets_equal_daily_for_the_same_unique_jobs(self, client) -> None:
        workflow_id = "wf-variant-calling-v1"
        timeline = call(
            client, "invocations/timeline", bucket="day", workflow_id=workflow_id, timezone="UTC"
        )
        daily = call(client, "daily", workflow_id=workflow_id, timezone="UTC")
        by_day = {bucket["from"][:10]: Decimal(bucket["amount"]) for bucket in timeline["buckets"]}
        expected = {item["date"]: Decimal(item["amount"]) for item in daily["items"]}
        assert by_day.keys() == expected.keys() and by_day
        for day, amount in expected.items():
            assert abs(by_day[day] - amount) < TOLERANCE

    def test_a_run_spanning_midnight_appears_in_each_day_it_used(self, client) -> None:
        edge = [
            run for run in every_run(client, search="rna")
            if run["started_at"].startswith("2026-08-31")
        ]
        assert edge
        timeline = call(client, "invocations/timeline", bucket="day", invocation_id=edge[0]["id"])
        days = [bucket["from"][:10] for bucket in timeline["buckets"]]
        assert "2026-08-31" in days and "2026-09-01" in days
        total = known(Decimal(bucket["amount"]) for bucket in timeline["buckets"])
        assert abs(total - Decimal(edge[0]["amount"])) < TOLERANCE

    def test_the_bucket_follows_the_period_length(self, client) -> None:
        def resolved(start: str, end: str) -> str:
            return call(
                client, "invocations/timeline", period=False, **{"from": start, "to": end}
            )["bucket"]

        assert resolved("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z") == "hour"
        assert resolved("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z") == "day"
        assert resolved("2026-09-01T00:00:00Z", "2026-09-08T00:00:00Z") == "day"
        assert resolved("2026-08-01T00:00:00Z", "2026-11-01T00:00:00Z") == "day"
        assert resolved("2026-08-01T00:00:00Z", "2026-11-02T00:00:00Z") == "week"

    def test_an_explicit_bucket_overrides_the_automatic_one(self, client) -> None:
        weekly = call(client, "invocations/timeline", bucket="week")
        assert weekly["bucket"] == "week"
        for bucket in weekly["buckets"]:
            assert datetime.fromisoformat(bucket["from"]).weekday() == 0
        assert call(client, "invocations/timeline", bucket="hour")["bucket"] == "hour"

    def test_pieces_are_capped_and_the_rest_fold_into_a_remainder(self, client) -> None:
        timeline = call(client, "invocations/timeline", bucket="week")
        assert all(len(bucket["pieces"]) <= 60 for bucket in timeline["buckets"])
        for bucket in timeline["buckets"]:
            pieces = known(Decimal(piece["amount"]) for piece in bucket["pieces"]) or Decimal(0)
            assert abs(pieces + Decimal(bucket["remainder"]["amount"]) - Decimal(bucket["amount"])) < TOLERANCE

    def test_a_bucket_holding_a_running_run_is_provisional(self, client) -> None:
        running = [run for run in every_run(client) if run["run_status"] == "running"]
        timeline = call(client, "invocations/timeline", bucket="day")
        assert any(bucket["provisional"] for bucket in timeline["buckets"])
        assert running

    def test_an_unbounded_timeline_reconciles_with_its_undated_subtotal(self, client) -> None:
        timeline = call(client, "invocations/timeline", period=False, bucket="day")
        totals = call(client, "invocations", period=False, limit=1)["totals"]
        drawn = known(Decimal(bucket["amount"]) for bucket in timeline["buckets"])
        unplaced = timeline["unplaced"]
        # The demonstration has runs whose last job left no evidence of timing.
        assert unplaced and unplaced["job_count"] >= 1
        beside = Decimal(unplaced["amount"]) if unplaced["amount"] is not None else Decimal(0)
        assert abs(drawn + beside - Decimal(totals["amount"])) < TOLERANCE

    def test_a_dated_timeline_has_no_unplaced_subtotal(self, client) -> None:
        assert call(client, "invocations/timeline")["unplaced"] is None

    def test_the_axis_covers_every_bucket(self, client) -> None:
        timeline = call(client, "invocations/timeline", bucket="day")
        assert timeline["axis"]["from"] <= timeline["buckets"][0]["from"]
        assert timeline["axis"]["to"] >= timeline["buckets"][-1]["to"]


class TestSafety:
    def test_a_viewer_sees_none_of_anothers_runs_on_any_endpoint(self, client) -> None:
        owners = owners_of_runs()
        bobs = {run_id for run_id, owner in owners.items() if owner == "bob"}
        assert bobs
        listing = every_run_as(client, "bob")
        assert listing and {run["id"] for run in listing} <= bobs
        breakdown = call(client, "invocations/breakdown", user="bob", admin=False)
        timeline = call(client, "invocations/timeline", user="bob", admin=False, bucket="day")
        assert {run["id"] for g in breakdown["groups"] for run in g["runs"]} <= bobs
        assert {p["id"] for b in timeline["buckets"] for p in b["pieces"]} <= bobs
        page = call(client, "invocations", user="bob", admin=False, limit=1)
        assert page["totals"]["run_count"] == len(listing)
        assert page["totals"]["unfiltered_run_count"] == len(listing)
        assert sum(option["run_count"] for option in page["filter_options"]["workflows"]) == len(listing)
        assert sum(page["filter_options"]["by_status"].values()) == len(listing)

    def test_another_viewers_run_cannot_be_asked_for_by_id(self, client) -> None:
        owners = owners_of_runs()
        alices = next(run_id for run_id, owner in owners.items() if owner == "alice")
        assert call(client, "invocations", user="bob", admin=False, invocation_id=alices)["items"] == []
        response = client.get(
            f"/api/invocations/{alices}", params=PERIOD, headers=run_headers("bob", False)
        )
        assert response.status_code == 404

    def test_bobs_totals_are_the_cost_of_his_own_jobs_only(self, client) -> None:
        page = call(client, "invocations", user="bob", admin=False, limit=200)
        ids = [run["id"] for run in page["items"]]
        members = set().union(*(demo_roots()[run_id] for run_id in ids))
        amounts = job_amounts_as(client, "bob")
        assert Decimal(page["totals"]["amount"]) == known(amounts.get(job) for job in members)

    def test_a_run_without_timing_stays_out_of_a_dated_period(self, client) -> None:
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == "anvil-demo"))
            bob = session.scalar(select(Job).where(Job.tenant_id == tenant.id, Job.source_id == "21"))
            invocation = Invocation(
                id=uuid.uuid4(), tenant_id=tenant.id, owner_id=bob.owner_id,
                source_id="run-without-timing", workflow_id="wf-untimed", workflow_family_id="fam-untimed",
                workflow_name="Untimed run", state="scheduled",
                created_at=datetime(2026, 9, 19, 13, 36, tzinfo=UTC),
            )
            session.add(invocation)
            session.flush()
            session.add(InvocationJob(
                invocation_id=invocation.id, job_id=bob.id, step_key="only", relationship="direct"
            ))
            calculate_tenant(session, tenant.id, reason="untimed run")
            session.commit()
        dated = {"from": "2026-09-19T00:00:00Z", "to": "2026-09-21T00:00:00Z"}
        found = client.get(
            "/api/invocations", params={**dated, "search": "untimed"}, headers=headers("bob")
        ).json()
        assert found["items"] == []
        assert found["meta"]["undated"]["job_count"] >= 1
        unbounded = client.get(
            "/api/invocations", params={"search": "untimed"}, headers=headers("bob")
        ).json()
        assert [run["source_id"] for run in unbounded["items"]] == ["run-without-timing"]
        with Session(engine) as session:
            session.delete(session.scalar(select(Invocation).where(Invocation.source_id == "run-without-timing")))
            session.commit()


def every_run_as(client, user: str) -> list[dict]:
    runs, offset = [], 0
    while True:
        page = call(client, "invocations", user=user, admin=False, limit=200, offset=offset)
        runs += page["items"]
        offset += 200
        if offset >= page["total"]:
            return runs


def job_amounts_as(client, user: str) -> dict[str, Decimal | None]:
    amounts, offset = {}, 0
    while True:
        page = call(client, "jobs", user=user, admin=False, limit=200, offset=offset)
        amounts |= {
            item["id"]: Decimal(item["amount"]) if item["amount"] is not None else None
            for item in page["items"]
        }
        offset += 200
        if offset >= page["total"]:
            return amounts


class TestContract:
    def test_bad_selections_are_rejected(self, client) -> None:
        for params in (
            {"focus_from": "2026-09-02T00:00:00Z"},
            {"focus_from": "2026-09-03T00:00:00Z", "focus_to": "2026-09-02T00:00:00Z"},
            {"focus_from": "2026-07-01T00:00:00Z", "focus_to": "2026-07-02T00:00:00Z"},
            {"focus_from": "2026-09-02T00:00:00", "focus_to": "2026-09-03T00:00:00Z"},
            {"max_run_amount": "1", "boundary_run_id": str(uuid.uuid4())},
            {"workflow_key": "w", "max_run_amount": "1"},
            {"workflow_key": "w", "max_run_amount": "-1", "boundary_run_id": str(uuid.uuid4())},
            {"workflow_key": "w", "max_run_amount": "1", "boundary_run_id": "not-a-uuid"},
            {"run_status": "paused"},
            {"run_sort": "colour"},
            {"bucket": "fortnight"},
            {"limit": 201},
        ):
            for path in ("invocations", "invocations/breakdown", "invocations/timeline"):
                response = client.get(
                    f"/api/{path}", params={**PERIOD, **params}, headers=run_headers()
                )
                assert response.status_code == 422, (path, params)

    def test_the_shared_endpoints_keep_their_own_default_page(self, client) -> None:
        assert call(client, "jobs")["limit"] == 50

    def test_a_stale_snapshot_is_rejected_by_all_three_endpoints(self, client) -> None:
        pinned = call(client, "summary")["revision_id"]
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            current = session.get(CostRevision, tenant.id)
            current.id = uuid.uuid4()
            session.commit()
            tenant_id = tenant.id
        try:
            for path in ("invocations", "invocations/breakdown", "invocations/timeline"):
                response = client.get(
                    f"/api/{path}", params={**PERIOD, "revision": pinned}, headers=run_headers()
                )
                assert response.status_code == 409, path
        finally:
            with Session(engine) as session:
                session.get(CostRevision, tenant_id).id = uuid.UUID(pinned)
                session.commit()

    def test_a_malformed_revision_is_rejected(self, client) -> None:
        for path in ("invocations", "invocations/breakdown", "invocations/timeline"):
            response = client.get(
                f"/api/{path}", params={**PERIOD, "revision": "nope"}, headers=run_headers()
            )
            assert response.status_code == 422

    def test_the_literal_routes_are_not_read_as_a_run_id(self, client) -> None:
        response = client.get("/api/invocations/breakdown", params=PERIOD, headers=run_headers())
        assert response.status_code == 200 and "groups" in response.json()
