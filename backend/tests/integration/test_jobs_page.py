"""The Jobs page endpoints, against the generated demonstration runs."""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from rainstone.costing import calculate_tenant
from rainstone.db import engine
from rainstone.models import Invocation, InvocationJob, Job, Owner, Tenant
from sqlalchemy import select
from sqlalchemy.orm import Session

from .conftest import RUNS_TENANT, run_headers
from .test_run_endpoints import PERIOD, TOLERANCE, call, demo_roots, job_amounts, known

FASTQC = "toolshed.g2.bx.psu.edu/repos/devteam/fastqc/fastqc"
STATUSES = {"completed", "running", "failed", "other"}


def amount(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def pieces_total(pieces: list[dict]) -> Decimal | None:
    return known(amount(piece["amount"]) for piece in pieces)


def every_job(client, **params) -> list[dict]:
    jobs, offset = [], 0
    while True:
        page = call(client, "jobs", limit=200, offset=offset, **params)
        jobs += page["items"]
        offset += 200
        if offset >= page["total"]:
            return jobs


def everything(client, **params) -> dict:
    return call(client, "jobs/breakdown", group_limit=10000, **params)


@contextmanager
def changed_tools(changes: dict[str, tuple[str, str | None]]):
    """Give some demonstration jobs another tool identity for the length of a test."""
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
        original = {}
        for source_id, (tool_id, version) in changes.items():
            job = session.scalar(select(Job).where(Job.tenant_id == tenant.id, Job.source_id == source_id))
            original[source_id] = (job.tool_id, job.tool_version)
            job.tool_id, job.tool_version = tool_id, version
        calculate_tenant(session, tenant.id, reason="changed tools")
        session.commit()
        tenant_id = tenant.id
    try:
        yield
    finally:
        with Session(engine) as session:
            for source_id, (tool_id, version) in original.items():
                job = session.scalar(select(Job).where(Job.tenant_id == tenant_id, Job.source_id == source_id))
                job.tool_id, job.tool_version = tool_id, version
            calculate_tenant(session, tenant_id, reason="restored tools")
            session.commit()


def fastqc_jobs(count: int) -> list[str]:
    with Session(engine) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
        return list(session.scalars(
            select(Job.source_id).where(Job.tenant_id == tenant.id, Job.tool_id.startswith(FASTQC))
            .order_by(Job.source_id).limit(count)
        ))


class TestBreakdown:
    def test_the_totals_are_the_overview_headline(self, client) -> None:
        totals = call(client, "jobs/breakdown")["totals"]
        summary = call(client, "summary")
        assert Decimal(totals["amount"]) == Decimal(summary["amount"])
        assert totals["job_count"] == summary["job_count"]
        assert totals["tool_count"] == len({job["tool_key"] for job in every_job(client)})
        assert sum(piece["job_count"] for piece in totals["by_status"]) == totals["job_count"]
        assert pieces_total(totals["by_status"]) == Decimal(totals["amount"])

    def test_every_tool_and_job_is_accounted_for_once(self, client) -> None:
        result = call(client, "jobs/breakdown", group_limit=3)
        sections = [result["server"], result["zero"], result["unavailable"]]
        assert result["ranked_tool_count"] == result["total"] > 3
        assert len(result["groups"]) == 3
        tools = 3 + result["remainder"]["tool_count"] + sum(s["tool_count"] for s in sections)
        jobs = (
            sum(group["job_count"] for group in result["groups"]) + result["remainder"]["job_count"]
            + sum(s["job_count"] for s in sections)
        )
        assert tools == result["totals"]["tool_count"]
        assert jobs == result["totals"]["job_count"]

    def test_the_remainder_is_every_tool_not_shown(self, client) -> None:
        shown = call(client, "jobs/breakdown", group_limit=3)
        whole = everything(client)
        assert [group["key"] for group in whole["groups"][:3]] == [group["key"] for group in shown["groups"]]
        rest = known(amount(group["amount"]) for group in whole["groups"][3:])
        assert Decimal(shown["remainder"]["amount"]) == rest
        ranked = known(amount(group["amount"]) for group in whole["groups"])
        assert abs(ranked - Decimal(whole["totals"]["amount"])) < TOLERANCE
        assert shown["scale"] == whole["groups"][0]["amount"]

    def test_tools_are_ranked_by_cost_then_key(self, client) -> None:
        groups = everything(client)["groups"]
        order = [(-Decimal(group["amount"]), group["key"]) for group in groups]
        assert order == sorted(order)
        assert all(Decimal(group["amount"]) > 0 and group["category"] == "ranked" for group in groups)

    def test_status_pieces_add_up_to_each_tool(self, client) -> None:
        for group in everything(client)["groups"]:
            assert {piece["status"] for piece in group["by_status"]} <= STATUSES
            assert pieces_total(group["by_status"]) == Decimal(group["amount"])
            assert sum(piece["job_count"] for piece in group["by_status"]) == group["job_count"]

    def test_finding_a_tool_reaches_rows_not_shown_and_leaves_the_totals(self, client) -> None:
        whole = everything(client)
        hidden = whole["groups"][-1]
        found = call(client, "jobs/breakdown", group_limit=2, tool_search=hidden["name"].upper())
        assert hidden["key"] in {group["key"] for group in found["groups"]}
        assert found["totals"] == whole["totals"]
        assert found["scale"] == whole["scale"]
        assert found["ranked_tool_count"] == whole["ranked_tool_count"]

    def test_versions_of_one_tool_are_one_row_and_names_alone_never_merge(self, client) -> None:
        older, local = fastqc_jobs(2)
        with changed_tools({older: (f"{FASTQC}/0.73", "0.73"), local: ("fastqc", None)}):
            groups = {group["key"]: group for group in everything(client)["groups"]}
            family = groups[FASTQC]
            assert {version["version"] for version in family["versions"]} >= {"0.73", "0.74+galaxy1"}
            assert f"{FASTQC}/0.73" in family["tool_ids"]
            # A local tool with the same readable name is a different tool.
            assert "fastqc" in groups and groups["fastqc"]["name"] == family["name"]
            version_only = call(client, "jobs", tool_key=FASTQC, tool_version="0.73")
            assert version_only["total"] == 1
            exact = call(client, "jobs", tool_id=f"{FASTQC}/0.73")
            assert [job["source_id"] for job in exact["items"]] == [older]

    def test_a_tool_shed_id_whose_version_disagrees_keeps_its_identity(self, client) -> None:
        (job,) = fastqc_jobs(1)
        with changed_tools({job: (f"{FASTQC}/0.73", "0.72")}):
            keys = {group["key"] for group in everything(client)["groups"]}
            assert f"{FASTQC}/0.73" in keys


class TestToolFilter:
    def test_the_family_filter_reaches_every_report(self, client) -> None:
        group = everything(client)["groups"][0]
        key = group["key"]
        assert Decimal(call(client, "summary", tool_key=key)["amount"]) == Decimal(group["amount"])
        jobs = every_job(client, tool_key=key)
        assert len(jobs) == group["job_count"] and {job["tool_key"] for job in jobs} == {key}
        filtered = call(client, "jobs/breakdown", tool_key=key)
        assert [g["key"] for g in filtered["groups"]] == [key]
        timeline = call(client, "jobs/timeline", tool_key=key)
        assert Decimal(timeline["totals"]["amount"]) == Decimal(group["amount"])
        export = client.get(
            "/api/export/jobs.csv", params={**PERIOD, "tool_key": key}, headers=run_headers()
        )
        assert export.status_code == 200
        assert len(export.text.strip().splitlines()) == group["job_count"] + 1

    def test_the_displayed_name_is_searchable(self, client) -> None:
        jobs = every_job(client, search="bwa mem")
        assert jobs and all(job["tool_name"] == "bwa mem" for job in jobs)


class TestTimeline:
    def test_columns_add_up_to_the_total_and_match_overview(self, client) -> None:
        result = call(client, "jobs/timeline", bucket="day", timezone="UTC")
        drawn = known(amount(bucket["amount"]) for bucket in result["buckets"])
        assert abs(drawn - Decimal(result["totals"]["amount"])) < TOLERANCE
        overview = {
            bucket["from"]: bucket["amount"]
            for bucket in call(client, "timeline", bucket="day", timezone="UTC")["buckets"]
        }
        assert {bucket["from"]: bucket["amount"] for bucket in result["buckets"]} == overview

    def test_status_pieces_add_up_to_each_column(self, client) -> None:
        for bucket in call(client, "jobs/timeline", bucket="day")["buckets"]:
            assert pieces_total(bucket["by_status"]) == amount(bucket["amount"])
            assert [p["status"] for p in bucket["by_status"]] == [
                status for status in ("completed", "running", "failed", "other")
                if status in {p["status"] for p in bucket["by_status"]}
            ]
            assert max(piece["job_count"] for piece in bucket["by_status"]) <= bucket["job_count"]

    def test_the_bucket_follows_the_shared_rule(self, client) -> None:
        day = {"from": "2026-09-02T00:00:00Z", "to": "2026-09-03T00:00:00Z"}
        assert call(client, "jobs/timeline", period=False, **day)["bucket"] == "hour"
        assert call(client, "jobs/timeline")["bucket"] == "day"
        wide = {"from": "2026-01-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"}
        assert call(client, "jobs/timeline", period=False, **wide)["bucket"] == "week"


class TestToolDetail:
    def test_contributors_are_the_costliest_complete_jobs_of_the_whole_tool(self, client) -> None:
        group = everything(client)["groups"][0]
        detail = call(client, "jobs/tool-detail", tool_key=group["key"])
        assert detail["amount"] == group["amount"] and detail["job_count"] == group["job_count"]
        contributors = detail["contributors"]
        assert contributors["kind"] == "ranked" and len(contributors["jobs"]) <= 5
        jobs = every_job(client, tool_key=group["key"])
        complete = [job for job in jobs if job["quality"] in {"complete", "approximate", "known_zero"}]
        expected = sorted(complete, key=lambda job: (-Decimal(job["amount"]), job["id"]))[:5]
        assert [job["id"] for job in contributors["jobs"]] == [job["id"] for job in expected]
        assert contributors["eligible_job_count"] == len(complete)
        assert contributors["excluded_job_count"] == len(jobs) - len(complete)

    def test_incomplete_jobs_are_excluded_and_counted(self, client) -> None:
        groups = [g for g in everything(client)["groups"] if g["incomplete_job_count"]]
        assert groups
        detail = call(client, "jobs/tool-detail", tool_key=groups[0]["key"])
        assert detail["contributors"]["excluded_job_count"] == groups[0]["incomplete_job_count"]
        ranked = {job["id"] for job in detail["contributors"]["jobs"]}
        incomplete = {
            job["id"] for job in every_job(client, tool_key=groups[0]["key"])
            if job["quality"] not in {"complete", "approximate", "known_zero"}
        }
        assert not ranked & incomplete

    def test_rows_carry_the_period_cost_and_the_whole_duration(self, client) -> None:
        group = everything(client)["groups"][0]
        row = call(client, "jobs/tool-detail", tool_key=group["key"])["contributors"]["jobs"][0]
        detail = call(client, f"jobs/{row['id']}")
        assert row["amount"] == detail["interval_amount"]
        assert row["duration_seconds"] == detail["duration_seconds"]

    def test_a_tool_with_no_matching_jobs_is_empty_not_an_error(self, client) -> None:
        detail = call(client, "jobs/tool-detail", tool_key="no/such/tool")
        assert detail["job_count"] == 0 and detail["amount"] is None
        assert detail["contributors"]["kind"] == "unavailable"


class TestWindowDetail:
    def test_an_interval_matches_its_column(self, client) -> None:
        buckets = call(client, "jobs/timeline", bucket="day")["buckets"]
        bucket = max(buckets, key=lambda value: value["job_count"])
        window = {"window_from": bucket["from"], "window_to": bucket["to"]}
        detail = call(client, "jobs/window-detail", limit=5, **window)
        assert detail["amount"] == bucket["amount"] or abs(
            Decimal(detail["amount"]) - Decimal(bucket["amount"])) < TOLERANCE
        assert detail["job_count"] == detail["total"] == bucket["job_count"]
        assert detail["incomplete_job_count"] == bucket["incomplete_job_count"]

    def test_paging_never_changes_the_totals(self, client) -> None:
        buckets = call(client, "jobs/timeline", bucket="day")["buckets"]
        bucket = max(buckets, key=lambda value: value["job_count"])
        window = {"window_from": bucket["from"], "window_to": bucket["to"]}
        first = call(client, "jobs/window-detail", limit=3, **window)
        second = call(client, "jobs/window-detail", limit=3, offset=3, **window)
        assert {k: first[k] for k in ("amount", "job_count", "by_status")} == {
            k: second[k] for k in ("amount", "job_count", "by_status")
        }
        every = call(client, "jobs/window-detail", limit=200, **window)["items"]
        assert [job["id"] for job in every[:6]] == [job["id"] for job in first["items"] + second["items"]]
        order = [(amount(job["amount"]) is None, -(amount(job["amount"]) or 0), job["id"]) for job in every]
        assert order == sorted(order)

    def test_the_interval_is_clipped_to_the_period(self, client) -> None:
        day = {"from": "2026-09-02T00:00:00Z", "to": "2026-09-03T00:00:00Z"}
        detail = call(
            client, "jobs/window-detail", period=False, **day,
            window_from="2026-09-01T00:00:00Z", window_to="2026-09-02T06:00:00Z",
        )
        assert detail["from"].startswith("2026-09-02T00:00") and detail["to"].startswith("2026-09-02T06:00")

    def test_a_page_cost_filter_is_judged_over_the_period(self, client) -> None:
        buckets = call(client, "jobs/timeline", bucket="hour",
                       period=False, **{"from": "2026-09-02T00:00:00Z", "to": "2026-09-03T00:00:00Z"})["buckets"]
        bucket = max(buckets, key=lambda value: value["job_count"])
        params = {"period": False, "from": "2026-09-02T00:00:00Z", "to": "2026-09-03T00:00:00Z"}
        page = every_job(client, min_cost="0.000001", **params)
        detail = call(
            client, "jobs/window-detail", min_cost="0.000001", limit=200,
            window_from=bucket["from"], window_to=bucket["to"], **params,
        )
        assert {job["id"] for job in detail["items"]} <= {job["id"] for job in page}

    def test_bad_intervals_are_rejected(self, client) -> None:
        for window in (
            {"window_from": "2026-09-03T00:00:00Z", "window_to": "2026-09-02T00:00:00Z"},
            {"window_from": "2026-09-02T00:00:00", "window_to": "2026-09-03T00:00:00Z"},
            {"window_from": "2025-01-01T00:00:00Z", "window_to": "2025-01-02T00:00:00Z"},
        ):
            response = client.get(
                "/api/jobs/window-detail", params={**PERIOD, **window}, headers=run_headers()
            )
            assert response.status_code == 422, window


class TestJobRows:
    def test_origin_agrees_with_overview(self, client) -> None:
        jobs = every_job(client)
        in_a_run = set().union(*demo_roots().values())
        assert {job["id"] for job in jobs if job["origin"] == "workflow"} == in_a_run & {j["id"] for j in jobs}
        individual = call(client, "timeline")["totals"]["individual_job_count"]
        assert sum(job["origin"] != "workflow" for job in jobs) == individual

    def test_a_workflow_job_names_the_earliest_run_that_holds_it(self, client) -> None:
        roots = demo_roots()
        runs = {run["id"]: run for run in call(client, "invocations", limit=200)["items"]}
        with Session(engine) as session:
            created = {str(inv.id): inv.created_at for inv in session.scalars(select(Invocation))}
        shared = 0
        for job in every_job(client):
            holders = sorted((r for r, jobs in roots.items() if job["id"] in jobs), key=lambda r: (created[r], r))
            if job["origin"] != "workflow":
                assert job["origin_run"] is None and job["origin_run_count"] == 0
                continue
            assert job["origin_run"]["id"] == holders[0]
            assert job["origin_run_count"] == len(holders)
            if holders[0] in runs:
                assert job["origin_run"]["workflow_name"] == runs[holders[0]]["workflow_name"]
            shared += len(holders) > 1
        assert shared > 0

    def test_a_link_the_viewer_cannot_trace_is_unknown_not_individual(self, client) -> None:
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            in_a_run = set().union(*demo_roots().values())
            alice = next(
                job for job in session.scalars(
                    select(Job).join(Owner, Job.owner_id == Owner.id)
                    .where(Job.tenant_id == tenant.id, Owner.source_id == "alice")
                ) if str(job.id) not in in_a_run
            )
            bobs_run = session.scalar(
                select(Invocation).join(Owner, Invocation.owner_id == Owner.id)
                .where(Invocation.tenant_id == tenant.id, Owner.source_id == "bob").limit(1)
            )
            session.add(InvocationJob(
                invocation_id=bobs_run.id, job_id=alice.id, step_key="foreign-origin", relationship="direct"
            ))
            calculate_tenant(session, tenant.id, reason="foreign membership")
            session.commit()
            alice_id = str(alice.id)
        try:
            jobs = every_job(client, user="alice", admin=False)
            assert next(job for job in jobs if job["id"] == alice_id)["origin"] == "unknown"
        finally:
            with Session(engine) as session:
                session.delete(session.scalar(
                    select(InvocationJob).where(InvocationJob.step_key == "foreign-origin")
                ))
                session.commit()

    def test_a_run_still_adding_jobs_leaves_later_jobs_unknown(self, client) -> None:
        with Session(engine) as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == RUNS_TENANT))
            owner = session.scalar(select(Owner).where(Owner.tenant_id == tenant.id, Owner.source_id == "bob"))
            session.add(Invocation(
                id=uuid.uuid4(), tenant_id=tenant.id, owner_id=owner.id, source_id="unsettled-run",
                workflow_name="Still scheduling", state="new", membership_settled=False,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            ))
            calculate_tenant(session, tenant.id, reason="unsettled run")
            session.commit()
        try:
            jobs = every_job(client, user="bob", admin=False)
            assert {job["origin"] for job in jobs} <= {"workflow", "unknown"}
            assert any(job["origin"] == "unknown" for job in jobs)
        finally:
            with Session(engine) as session:
                session.delete(session.scalar(select(Invocation).where(Invocation.source_id == "unsettled-run")))
                session.commit()

    def test_duration_matches_the_job_detail(self, client) -> None:
        for job in call(client, "jobs", limit=20)["items"]:
            detail = call(client, f"jobs/{job['id']}")
            assert job["duration_seconds"] == detail["duration_seconds"]
            assert job["duration_running"] == detail["duration_running"]

    def test_a_viewer_sees_only_their_own_jobs_in_every_view(self, client) -> None:
        mine = job_amounts(client, user="bob", admin=False)
        totals = call(client, "jobs/breakdown", user="bob", admin=False)["totals"]
        assert totals["job_count"] == len(mine)
        assert Decimal(totals["amount"]) == known(mine.values())
        timeline = call(client, "jobs/timeline", user="bob", admin=False)["totals"]
        assert timeline == totals
        group = call(client, "jobs/breakdown", group_limit=1)["groups"][0]
        detail = call(client, "jobs/tool-detail", user="bob", admin=False, tool_key=group["key"])
        assert {job["id"] for job in detail["contributors"]["jobs"]} <= set(mine)
