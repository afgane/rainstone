"""What lies behind an Overview figure, against the generated demonstration runs."""

from decimal import Decimal

import pytest

from .conftest import run_headers
from .test_overview_timeline import timeline
from .test_run_endpoints import PERIOD, TOLERANCE, call, demo_roots, job_amounts, known


def details(client, scope, kind, user="admin", admin=True, **params):
    return call(client, "overview/details", user=user, admin=admin, scope=scope, kind=kind, **params)


def every_item(client, scope, kind, **params) -> list[dict]:
    items, offset = [], 0
    while True:
        page = details(client, scope, kind, limit=200, offset=offset, **params)
        items += page["items"]
        offset += 200
        if offset >= page["total"]:
            return items


def blocks(client, kind, **params):
    """Every chart block of one kind, with the bounds of the column it is in."""
    result = timeline(client, **params)
    return [
        (bucket, piece) for bucket in result["buckets"]
        for piece in bucket["pieces"] if piece["kind"] == kind
    ]


def window(bucket) -> dict:
    return {"window_from": bucket["from"], "window_to": bucket["to"]}


class TestIntervals:
    @pytest.mark.parametrize("kind", ["runs", "individual"])
    @pytest.mark.parametrize("bucket", ["hour", "day", "week"])
    def test_an_interval_reconciles_with_its_block(self, client, kind, bucket) -> None:
        found = blocks(client, kind, bucket=bucket)
        assert found
        for column, piece in found[:6]:
            detail = details(client, "interval", kind, **window(column))
            assert abs(Decimal(detail["amount"]) - Decimal(piece["amount"])) < TOLERANCE
            assert detail["job_count"] == piece["job_count"]
            if kind == "runs":
                assert detail["run_count"] == piece["run_count"] == detail["total"]

    @pytest.mark.parametrize("mode", ["accrued", "completed"])
    def test_both_modes_reconcile(self, client, mode) -> None:
        for kind in ("runs", "individual"):
            for column, piece in blocks(client, kind, bucket="day", mode=mode)[:4]:
                detail = details(client, "interval", kind, mode=mode, **window(column))
                assert abs(Decimal(detail["amount"]) - Decimal(piece["amount"])) < TOLERANCE

    def test_a_daylight_saving_day_reconciles(self, client) -> None:
        # Chile's clocks move forward on Sep 6, 2026, so that local day is 23 hours long.
        zone = {"timezone": "America/Santiago"}
        found = blocks(client, "runs", bucket="day", **zone) + blocks(client, "individual", bucket="day", **zone)
        found.sort(key=lambda entry: not entry[0]["from"].startswith("2026-09-06"))
        assert found
        for column, piece in found[:8]:
            detail = details(client, "interval", piece["kind"], **zone, **window(column))
            assert abs(Decimal(detail["amount"]) - Decimal(piece["amount"])) < TOLERANCE

    def test_a_shared_filter_narrows_the_interval_as_it_narrows_the_chart(self, client) -> None:
        for column, piece in blocks(client, "runs", bucket="day", runner="gcp_batch")[:4]:
            detail = details(client, "interval", "runs", runner="gcp_batch", **window(column))
            assert abs(Decimal(detail["amount"]) - Decimal(piece["amount"])) < TOLERANCE

    def test_run_contributions_add_up_to_the_block(self, client) -> None:
        column, piece = max(blocks(client, "runs", bucket="week"), key=lambda e: e[1]["run_count"])
        rows = every_item(client, "interval", "runs", **window(column))
        assert len(rows) == piece["run_count"] > 1
        counted = known(Decimal(row["amount"]) if row["amount"] else None for row in rows)
        assert abs(counted - Decimal(piece["amount"])) < TOLERANCE
        assert sum(row["job_count"] for row in rows) == piece["job_count"]
        amounts = [Decimal(row["amount"]) for row in rows if row["amount"] is not None]
        assert amounts == sorted(amounts, reverse=True)

    def test_a_run_row_is_its_counted_share_not_its_whole_total(self, client) -> None:
        column, _ = max(blocks(client, "runs", bucket="day"), key=lambda e: e[1]["run_count"])
        rows = every_item(client, "interval", "runs", **window(column))
        assert all(row["run_status"] for row in rows)
        assert any(
            row["run_total"] and row["amount"] and Decimal(row["run_total"]) > Decimal(row["amount"])
            for row in rows
        )

    def test_individual_jobs_hold_no_workflow_job(self, client) -> None:
        in_a_run = set().union(*demo_roots().values())
        for column, _ in blocks(client, "individual", bucket="week"):
            jobs = every_item(client, "interval", "individual", **window(column))
            assert jobs and not {job["id"] for job in jobs} & in_a_run

    def test_individual_jobs_are_ordered_known_cost_first(self, client) -> None:
        column, _ = max(blocks(client, "individual", bucket="week"), key=lambda e: e[1]["job_count"])
        jobs = every_item(client, "interval", "individual", **window(column))
        seen_unknown = False
        previous = None
        for job in jobs:
            if job["amount"] is None:
                seen_unknown = True
                continue
            assert not seen_unknown
            amount = Decimal(job["amount"])
            assert previous is None or amount <= previous
            previous = amount

    def test_pages_change_the_rows_only(self, client) -> None:
        column, _ = max(blocks(client, "individual", bucket="week"), key=lambda e: e[1]["job_count"])
        first = details(client, "interval", "individual", limit=2, **window(column))
        second = details(client, "interval", "individual", limit=2, offset=2, **window(column))
        assert first["total"] > 2
        for key in ("amount", "job_count", "incomplete_job_count", "total"):
            assert first[key] == second[key]
        assert not {job["id"] for job in first["items"]} & {job["id"] for job in second["items"]}

    def test_an_interval_is_clipped_to_the_period(self, client) -> None:
        detail = details(
            client, "interval", "individual",
            window_from="2026-07-20T00:00:00Z", window_to="2026-08-03T00:00:00Z",
        )
        assert detail["from"].startswith("2026-08-01")

    def test_bad_intervals_are_rejected(self, client) -> None:
        for params in (
            {"window_from": "2026-09-03T00:00:00Z", "window_to": "2026-09-02T00:00:00Z"},
            {"window_from": "2026-09-02T00:00:00", "window_to": "2026-09-03T00:00:00Z"},
            {"window_from": "2025-01-01T00:00:00Z", "window_to": "2025-01-02T00:00:00Z"},
            {},
        ):
            response = client.get("/api/overview/details", params={
                **PERIOD, "scope": "interval", "kind": "runs", **params,
            }, headers=run_headers())
            assert response.status_code == 422, params


class TestPeriod:
    def test_the_tools_headline_is_the_run_compute_headline(self, client) -> None:
        detail = details(client, "period", "tools")
        summary = call(client, "summary")
        assert Decimal(detail["amount"]) == Decimal(summary["amount"])
        assert detail["job_count"] == summary["job_count"]

    def test_the_runs_headline_covers_only_jobs_in_workflows(self, client) -> None:
        detail = details(client, "period", "runs")
        totals = timeline(client)["totals"]
        assert detail["job_count"] == totals["job_count"] - totals["individual_job_count"]
        in_a_run = set().union(*demo_roots().values())
        amounts = job_amounts(client)
        expected = known(amount for job, amount in amounts.items() if job in in_a_run)
        assert abs(Decimal(detail["amount"]) - expected) < TOLERANCE
        assert Decimal(detail["amount"]) < Decimal(call(client, "summary")["amount"])

    @pytest.mark.parametrize("kind", ["runs", "tools"])
    def test_a_ranking_lists_at_most_five_complete_positive_contributors(self, client, kind) -> None:
        detail = details(client, "period", kind)
        ranking = detail["ranking"]
        assert ranking["limit"] == 5 and len(detail["items"]) == min(5, ranking["eligible_count"])
        amounts = [Decimal(item["amount"]) for item in detail["items"]]
        assert all(amount > 0 for amount in amounts) and amounts == sorted(amounts, reverse=True)
        everyone = detail["run_count"] if kind == "runs" else detail["tool_count"]
        assert ranking["eligible_count"] + ranking["excluded_count"] + ranking["zero_count"] == everyone

    def test_the_run_ranking_considers_every_run_and_leaves_out_incomplete_ones(self, client) -> None:
        detail = details(client, "period", "runs")
        assert detail["run_count"] > 5 and detail["ranking"]["excluded_count"] > 0
        assert all(item["incomplete_job_count"] == 0 for item in detail["items"])
        # The ranking is the whole period's, not a page of the runs list's.
        page = call(client, "invocations", limit=3, run_sort="started_at")["items"]
        assert {item["id"] for item in detail["items"]} != {run["id"] for run in page}

    def test_tool_families_stay_distinct_across_versions(self, client) -> None:
        detail = details(client, "period", "tools")
        breakdown = call(client, "jobs/breakdown", group_limit=10000)
        families = {group["key"]: group for group in breakdown["groups"]}
        for item in detail["items"]:
            assert item["key"] in families
            assert item["amount"] == families[item["key"]]["amount"]

    def test_unsupported_combinations_are_rejected(self, client) -> None:
        for scope, kind in (("period", "individual"), ("interval", "tools"), ("day", "runs")):
            response = client.get("/api/overview/details", params={
                **PERIOD, "scope": scope, "kind": kind,
            }, headers=run_headers())
            assert response.status_code == 422, (scope, kind)


class TestSafety:
    def test_a_viewer_sees_only_their_own_work(self, client) -> None:
        mine = details(client, "period", "tools", user="bob", admin=False)
        summary = call(client, "summary", user="bob", admin=False)
        assert mine["job_count"] == summary["job_count"]
        everything = details(client, "period", "tools")
        assert mine["job_count"] < everything["job_count"]
        runs = details(client, "period", "runs", user="bob", admin=False)
        assert runs["run_count"] < details(client, "period", "runs")["run_count"]

    def test_a_stale_revision_is_refused(self, client) -> None:
        response = client.get("/api/overview/details", params={
            **PERIOD, "scope": "period", "kind": "runs",
            "revision": "00000000-0000-0000-0000-000000000000",
        }, headers=run_headers())
        assert response.status_code == 409
