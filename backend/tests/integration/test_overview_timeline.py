"""The Overview's cost over time, against the generated demonstration runs."""

import uuid
from datetime import datetime
from decimal import Decimal

from rainstone.db import engine
from rainstone.models import CostRevision, Tenant
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import RUNS_TENANT, run_headers
from .test_run_endpoints import PERIOD, TOLERANCE, call, demo_roots, job_amounts, known


def timeline(client, user="admin", admin=True, **params):
    return call(client, "timeline", user=user, admin=admin, **params)


class TestTotals:
    def test_the_totals_are_the_overview_headline(self, client) -> None:
        totals = timeline(client)["totals"]
        overview = call(client, "summary")
        assert Decimal(totals["amount"]) == Decimal(overview["amount"])
        assert totals["job_count"] == overview["job_count"]
        assert sum(totals["by_outcome"].values()) == totals["job_count"]
        assert totals["by_outcome"]["failed"] > 0 and totals["by_outcome"]["running"] > 0

    def test_the_columns_add_up_to_the_total(self, client) -> None:
        result = timeline(client, bucket="day")
        drawn = known(
            Decimal(bucket["amount"]) if bucket["amount"] is not None else None
            for bucket in result["buckets"]
        )
        assert abs(drawn - Decimal(result["totals"]["amount"])) < TOLERANCE
        assert result["unplaced"] is None

    def test_a_dated_columns_equal_the_daily_report_for_the_same_jobs(self, client) -> None:
        by_day = {
            bucket["from"][:10]: Decimal(bucket["amount"])
            for bucket in timeline(client, bucket="day", timezone="UTC")["buckets"]
        }
        expected = {
            item["date"]: Decimal(item["amount"])
            for item in call(client, "daily", timezone="UTC")["items"]
        }
        assert by_day.keys() == expected.keys() and by_day
        for day, amount in expected.items():
            assert abs(by_day[day] - amount) < TOLERANCE

    def test_runs_and_workflows_match_the_workflow_runs_page(self, client) -> None:
        totals = timeline(client)["totals"]
        runs = call(client, "invocations", limit=1)["totals"]
        assert totals["run_count"] == runs["run_count"]
        assert totals["workflow_count"] == runs["workflow_count"] == 8

    def test_individual_jobs_are_the_jobs_outside_every_run(self, client) -> None:
        totals = timeline(client)["totals"]
        in_a_run = set().union(*demo_roots().values())
        outside = [job for job in job_amounts(client) if job not in in_a_run]
        assert totals["individual_job_count"] == len(outside) > 0
        assert totals["job_count"] >= totals["individual_job_count"]


class TestGrouping:
    def test_each_column_has_a_block_for_workflow_runs_and_one_for_individual_jobs(self, client) -> None:
        result = timeline(client, bucket="day")
        pieces = [piece for bucket in result["buckets"] for piece in bucket["pieces"]]
        assert {piece["kind"] for piece in pieces} == {"runs", "individual"}
        assert {piece["name"] for piece in pieces if piece["kind"] == "runs"} == {"Workflow runs"}
        assert {piece["name"] for piece in pieces if piece["kind"] == "individual"} == {"Individual jobs"}
        # However many workflows there are, a column never holds more than two blocks.
        assert all(len(bucket["pieces"]) <= 2 for bucket in result["buckets"])
        assert all(piece["key"] == piece["kind"] for piece in pieces)

    def test_the_two_blocks_add_up_to_their_column(self, client) -> None:
        for bucket in timeline(client, bucket="day")["buckets"]:
            drawn = known(Decimal(piece["amount"]) for piece in bucket["pieces"]) or Decimal(0)
            assert abs(drawn - Decimal(bucket["amount"])) < TOLERANCE

    def test_a_block_reports_its_runs_jobs_and_outcomes(self, client) -> None:
        pieces = [p for b in timeline(client, bucket="day")["buckets"] for p in b["pieces"]]
        runs = next(p for p in pieces if p["kind"] == "runs")
        assert runs["run_count"] >= 1 and runs["job_count"] >= runs["run_count"]
        individual = next(p for p in pieces if p["kind"] == "individual")
        assert individual["run_count"] == 0 and individual["job_count"] >= 1
        assert any(p["failed"] for p in pieces)
        assert any(p["running"] for p in pieces)

    def test_jobs_in_runs_and_individual_jobs_make_up_every_job(self, client) -> None:
        totals = timeline(client)["totals"]
        in_a_run = set().union(*demo_roots().values())
        jobs_in_runs = len(in_a_run & set(job_amounts(client)))
        assert totals["job_count"] - totals["individual_job_count"] == jobs_in_runs > 0

    def test_a_column_counts_each_job_once(self, client) -> None:
        for bucket in timeline(client, bucket="day")["buckets"]:
            assert bucket["job_count"] >= max((p["job_count"] for p in bucket["pieces"]), default=0)
            assert bucket["failed_job_count"] <= bucket["job_count"]

    def test_a_bucket_holding_running_work_is_provisional(self, client) -> None:
        assert any(bucket["provisional"] for bucket in timeline(client, bucket="day")["buckets"])


class TestBuckets:
    def test_the_bucket_follows_the_period_length(self, client) -> None:
        def resolved(start: str, end: str) -> str:
            return call(client, "timeline", period=False, **{"from": start, "to": end})["bucket"]

        assert resolved("2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z") == "hour"
        assert resolved("2026-09-01T00:00:00Z", "2026-09-03T00:00:00Z") == "day"
        assert resolved("2026-08-01T00:00:00Z", "2026-11-02T00:00:00Z") == "week"

    def test_an_explicit_bucket_overrides_it(self, client) -> None:
        weekly = timeline(client, bucket="week")
        assert weekly["bucket"] == "week"
        assert all(datetime.fromisoformat(b["from"]).weekday() == 0 for b in weekly["buckets"])

    def test_the_axis_covers_every_column(self, client) -> None:
        result = timeline(client, bucket="day")
        assert result["axis"]["from"] <= result["buckets"][0]["from"]
        assert result["axis"]["to"] >= result["buckets"][-1]["to"]

    def test_an_empty_period_is_explicitly_empty(self, client) -> None:
        result = call(
            client, "timeline", period=False,
            **{"from": "2020-01-01T00:00:00Z", "to": "2020-01-08T00:00:00Z"},
        )
        assert result["buckets"] == [] and result["axis"] is None
        assert result["totals"]["job_count"] == 0 and result["totals"]["amount"] is None

    def test_an_unbounded_timeline_reconciles_with_its_unplaced_cost(self, client) -> None:
        result = call(client, "timeline", period=False, bucket="day")
        drawn = known(Decimal(b["amount"]) for b in result["buckets"])
        unplaced = result["unplaced"]
        assert unplaced and unplaced["job_count"] >= 1
        beside = Decimal(unplaced["amount"]) if unplaced["amount"] is not None else Decimal(0)
        assert abs(drawn + beside - Decimal(result["totals"]["amount"])) < TOLERANCE


class TestFiltersAndSafety:
    def test_shared_filters_narrow_the_chart_and_the_totals_together(self, client) -> None:
        everything = timeline(client)["totals"]
        narrowed = timeline(client, runner="gcp_batch")
        assert narrowed["totals"]["job_count"] < everything["job_count"]
        drawn = known(Decimal(b["amount"]) for b in narrowed["buckets"] if b["amount"] is not None)
        assert abs(drawn - Decimal(narrowed["totals"]["amount"])) < TOLERANCE

    def test_a_viewer_sees_only_their_own_work(self, client) -> None:
        mine = timeline(client, user="bob", admin=False)
        overview = call(client, "summary", user="bob", admin=False)
        assert mine["totals"]["job_count"] == overview["job_count"]
        assert Decimal(mine["totals"]["amount"]) == Decimal(overview["amount"])
        everything = timeline(client)["totals"]
        assert mine["totals"]["job_count"] < everything["job_count"]

    def test_bad_requests_are_rejected(self, client) -> None:
        response = client.get(
            "/api/timeline", params={**PERIOD, "bucket": "fortnight"}, headers=run_headers()
        )
        assert response.status_code == 422

    def test_a_stale_snapshot_is_rejected(self, client) -> None:
        pinned = call(client, "summary")["revision_id"]
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            session.get(CostRevision, tenant.id).id = uuid.uuid4()
            session.commit()
            tenant_id = tenant.id
        try:
            response = client.get(
                "/api/timeline", params={**PERIOD, "revision": pinned}, headers=run_headers()
            )
            assert response.status_code == 409
        finally:
            with Session(engine) as session:
                session.get(CostRevision, tenant_id).id = uuid.UUID(pinned)
                session.commit()
