#!/usr/bin/env python3
"""Generate a rolled-back 100k-job corpus and measure representative report calls."""

import argparse
import platform
import statistics
import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from rainstone.auth import Identity
from rainstone.costing import current_generation, report_fingerprint
from rainstone.db import engine
from rainstone.models import (
    CostLine,
    CostRevision,
    ExecutionAttempt,
    Invocation,
    InvocationJob,
    Job,
    LifetimeAttempt,
    Owner,
    Quality,
    ResourceLifetime,
    ResourceSegment,
    Tenant,
)
from rainstone.report_query import ReportQuery, RunReportQuery
from rainstone.reporting import breakdown, invocations, list_jobs, summary, timeline
from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

NS = uuid.UUID("547ec231-cf18-41f2-a76d-ae7c96146cbc")

TRIGGERED_TABLES = (
    "job",
    "execution_attempt",
    "resource_lifetime",
    "resource_segment",
    "lifetime_attempt",
)


def uid(kind: str, number: int) -> uuid.UUID:
    return uuid.uuid5(NS, f"{kind}:{number}")


# A medium deployment, which is what the reports are sized for.
JOB_COUNT = 10_000
RUN_COUNT = 500
WORKFLOW_COUNT = 12


def seed_runs(session: Session, tenant: Tenant, owner: Owner, jobs: int, runs: int) -> int:
    """Group the corpus into runs of mixed sizes, every tenth with a nested child.

    Run sizes cycle through 1 to 30 jobs, so a few runs are large and most are
    small. A nested run's child holds the second half of its jobs, which the
    root reaches through its child as well.
    """
    sizes = [1, 2, 3, 5, 8, 13, 21, 30]
    invocation_rows, membership_rows = [], []
    cursor = 0
    made = 0
    for number in range(runs):
        size = sizes[number % len(sizes)]
        if cursor + size > jobs:
            break
        members = range(cursor, cursor + size)
        cursor += size
        made += 1
        root_id = uid("run", number)
        slug = number % WORKFLOW_COUNT
        started = datetime.now(UTC) - timedelta(seconds=number % 2_592_000)
        invocation_rows.append({
            "id": root_id, "tenant_id": tenant.id, "owner_id": owner.id,
            "source_id": f"benchmark-run-{number:05d}", "workflow_id": f"workflow-{slug}-v{number % 3}",
            "workflow_family_id": f"family-{slug}", "parent_id": None,
            "workflow_name": f"Benchmark workflow {slug}", "workflow_version": str(number % 3),
            "state": "scheduled", "membership_settled": True, "created_at": started,
        })
        nested = number % 10 == 0 and size >= 8
        for position, job_number in enumerate(members):
            membership_rows.append({
                "invocation_id": root_id, "job_id": uid("job", job_number),
                "step_key": f"step-{position}", "relationship": "direct",
            })
        if nested:
            child_id = uid("child", number)
            invocation_rows.append({
                "id": child_id, "tenant_id": tenant.id, "owner_id": owner.id,
                "source_id": f"benchmark-run-{number:05d}-child",
                "workflow_id": f"workflow-{slug}-sub", "workflow_family_id": f"family-{slug}-sub",
                "parent_id": root_id, "workflow_name": f"Benchmark workflow {slug}, sub-step",
                "workflow_version": "1", "state": "scheduled", "membership_settled": True,
                "created_at": started,
            })
            for position, job_number in enumerate(list(members)[size // 2:]):
                membership_rows.append({
                    "invocation_id": child_id, "job_id": uid("job", job_number),
                    "step_key": f"sub-{position}", "relationship": "collection",
                })
    session.execute(insert(Invocation), invocation_rows)
    session.execute(insert(InvocationJob), membership_rows)
    session.flush()
    return made


def load_corpus(
    session: Session, job_count: int, started: datetime, run_target: int = RUN_COUNT
) -> tuple[Tenant, Owner, int]:
    """Add the synthetic jobs and runs to the demonstration tenant, in this transaction."""
    # The report-generation triggers fire once per write statement. This
    # benchmark measures report latency, not ingestion, so the synthetic
    # corpus is loaded with them suspended inside the rolled-back
    # transaction, and the revision's marker is set explicitly below.
    for table in TRIGGERED_TABLES:
        session.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "anvil-demo"))
    owner = session.scalar(select(Owner).where(Owner.tenant_id == tenant.id, Owner.source_id == "admin"))
    revision = session.get(CostRevision, tenant.id) or CostRevision(tenant_id=tenant.id)
    revision.id = uuid.uuid4()
    revision.calculation_version = "phase2b-benchmark"
    revision.input_digest = uuid.uuid4().hex * 2
    revision.reason = "rolled-back benchmark"
    revision.created_at = started
    session.add(revision)
    session.flush()
    batch_size = 2_000
    for base in range(0, job_count, batch_size):
        numbers = range(base, min(job_count, base + batch_size))
        jobs, attempts, lifetimes, segments, links, lines = [], [], [], [], [], []
        for number in numbers:
            job_id, attempt_id = uid("job", number), uid("attempt", number)
            lifetime_id, segment_id = uid("lifetime", number), uid("segment", number)
            when = started - timedelta(seconds=number % 2_592_000)
            jobs.append({
                "id": job_id, "tenant_id": tenant.id, "owner_id": owner.id,
                "source_id": f"benchmark-{number:06d}", "tool_id": f"benchmark/tool/{number % 10}",
                "tool_version": f"{number % 4}.0", "state": "ok", "runner": "gcp_batch",
                "destination": "benchmark", "created_at": when, "updated_at": when,
                "copied_from_source_id": None,
            })
            attempts.append({
                "id": attempt_id, "job_id": job_id, "source_attempt_id": "attempt-0",
                "parent_attempt_id": None, "runner": "gcp_batch", "external_id": f"bench-{number}",
                "outcome": "ok", "tool_started_at": when, "tool_finished_at": when + timedelta(seconds=60),
            })
            lifetimes.append({
                "id": lifetime_id, "tenant_id": tenant.id, "provider": "gcp",
                "resource_key": f"gce:benchmark/us-central1-a/{number}",
                "resource_uid": f"bench-vm-{number}", "project": "benchmark",
                "zone": "us-central1-a", "region": "us-central1",
                "machine_type": "n2-standard-2", "purchase_model": "on_demand",
                "capacity_relationship": "dedicated", "observed_start": when,
                "observed_end": when + timedelta(seconds=60), "timing_method": "benchmark",
                "requested_vcpu": Decimal("2"), "requested_memory_mib": Decimal("8192"), "facts": {},
            })
            segments.append({
                "id": segment_id, "lifetime_id": lifetime_id, "source_segment_id": "lifetime",
                "observed_start": when, "observed_end": when + timedelta(seconds=60),
                "timing_method": "benchmark", "facts": {},
            })
            links.append({
                "lifetime_id": lifetime_id, "attempt_id": attempt_id, "task_index": 0,
                "attempt_ordinal": 0, "correlation": "benchmark", "facts": {},
            })
            lines.append({
                "id": uid("line", number), "job_id": job_id,
                "attempt_id": attempt_id, "lifetime_id": lifetime_id, "basis": "additional",
                "component": "compute", "amount": Decimal("0.001618633333"), "currency": "USD",
                "quality": Quality.complete, "reason": "Synthetic reporting benchmark.",
                "price_version_id": None, "policy_id": None, "details": {},
            })
        session.execute(insert(Job), jobs)
        session.execute(insert(ExecutionAttempt), attempts)
        session.execute(insert(ResourceLifetime), lifetimes)
        session.execute(insert(ResourceSegment), segments)
        session.execute(insert(LifetimeAttempt), links)
        session.execute(insert(CostLine), lines)
        session.flush()
    for table in TRIGGERED_TABLES:
        session.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))
    run_count = seed_runs(session, tenant, owner, job_count, run_target)
    # A corpus inserted in one transaction has no planner statistics yet, and
    # without them the run queries pick plans no real, analysed database would.
    for table in (*TRIGGERED_TABLES, "invocation", "invocation_job", "cost_line", "owner"):
        session.execute(text(f"ANALYZE {table}"))
    revision.input_digest = report_fingerprint(session, tenant.id)
    revision.facts_generation = current_generation(session, tenant.id)
    session.flush()
    return tenant, owner, run_count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=int, default=JOB_COUNT)
    parser.add_argument("--runs", type=int, default=RUN_COUNT, help="Workflow runs to group jobs into")
    parser.add_argument("--output", type=Path, default=Path("docs/benchmark-results.md"))
    args = parser.parse_args()
    started = datetime.now(UTC)
    with Session(engine) as session:
        tenant, owner, run_count = load_corpus(session, args.jobs, started, args.runs)
        identity = Identity(
            tenant.id, owner.id, owner.source_id, owner.label, True, can_view_infrastructure=True
        )
        # One job in ten uses tool 3, so that is how many the search matches.
        matching = args.jobs // 10
        query = ReportQuery(search="benchmark/tool/3", runner="gcp_batch", limit=50, sort="amount")
        timings: dict[str, list[float]] = {"summary": [], "first_page": [], "deep_page": []}
        for _iteration in range(8):
            for name, call in (
                ("summary", lambda: summary(session, identity, query)),
                ("first_page", lambda: list_jobs(session, identity, query)),
                ("deep_page", lambda: list_jobs(session, identity, query.model_copy(update={"offset": max(0, matching - query.limit)}))),
            ):
                before = time.perf_counter()
                call()
                timings[name].append((time.perf_counter() - before) * 1000)
        # Runs cover the corpus's own 30 days, ending when it was generated.
        two_days = RunReportQuery(from_time=started - timedelta(days=2), to_time=started + timedelta(hours=1))
        ninety_days = RunReportQuery(
            from_time=started - timedelta(days=90), to_time=started + timedelta(days=1)
        )
        run_timings: dict[str, list[float]] = {
            "invocations_first_page": [], "invocations_deep_page": [], "breakdown_90_days": [],
            "timeline_hour_2_days": [], "timeline_day_90_days": [],
        }
        for _iteration in range(8):
            for name, call in (
                ("invocations_first_page", lambda: invocations(session, identity, ninety_days)),
                ("invocations_deep_page", lambda: invocations(
                    session, identity, ninety_days.model_copy(update={"offset": run_count - 20}),
                )),
                ("breakdown_90_days", lambda: breakdown(session, identity, ninety_days)),
                ("timeline_hour_2_days", lambda: timeline(
                    session, identity, two_days.model_copy(update={"bucket": "hour"}),
                )),
                ("timeline_day_90_days", lambda: timeline(
                    session, identity, ninety_days.model_copy(update={"bucket": "day"}),
                )),
            ):
                before = time.perf_counter()
                call()
                run_timings[name].append((time.perf_counter() - before) * 1000)
        generation_seconds = (datetime.now(UTC) - started).total_seconds()
        rows = [
            "# Rainstone reporting benchmark", "",
            f"- Generated jobs: {args.jobs:,} (transaction rolled back)",
            f"- Host: {platform.platform()} · {platform.machine()} · Python {platform.python_version()}",
            f"- PostgreSQL URL host: {engine.url.host}",
            f"- Corpus generation: {generation_seconds:.2f} s",
            f"- Query: runner=gcp_batch, search=benchmark/tool/3 ({matching:,} matching jobs), amount sort",
            "- Eight iterations; first is cold with respect to application objects, later runs are warm.",
            "- The corpus is loaded with the report-generation triggers suspended inside the "
            "rolled-back transaction: this measures report latency, not ingestion. Those triggers "
            "add one small upsert per write statement, so bulk backfill favors batched writes.", "",
            "| Request | Cold | Warm p50 | Warm p95 | Maximum |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        def table_rows(measured: dict[str, list[float]]) -> list[str]:
            lines = []
            for name, values in measured.items():
                warm = values[1:]
                ordered = sorted(warm)
                p95 = ordered[min(len(ordered) - 1, round(.95 * (len(ordered) - 1)))]
                lines.append(
                    f"| {name} | {values[0]:.1f} ms | {statistics.median(warm):.1f} ms "
                    f"| {p95:.1f} ms | {max(values):.1f} ms |"
                )
            return lines

        rows += table_rows(timings)
        plan = session.execute(text(
            "EXPLAIN (ANALYZE, BUFFERS) SELECT count(*) FROM job JOIN owner ON job.owner_id=owner.id "
            "WHERE job.tenant_id=:tenant AND job.runner='gcp_batch' "
            "AND (job.source_id ILIKE '%benchmark/tool/3%' OR job.tool_id ILIKE '%benchmark/tool/3%' "
            "OR coalesce(job.tool_version, '') ILIKE '%benchmark/tool/3%' "
            "OR owner.label ILIKE '%benchmark/tool/3%')"
        ), {"tenant": tenant.id}).scalars().all()
        rows += [
            "", f"## Workflow run requests ({run_count:,} runs)", "",
            "- Runs group the same corpus: sizes cycle through 1 to 30 jobs and every tenth "
            "large run has a nested child workflow.",
            "- `invocations_*` request 20 runs of the 90-day period (`invocations_deep_page` "
            "the last page); `breakdown_90_days` and `timeline_day_90_days` cover 90 days; "
            "`timeline_hour_2_days` covers the last two days by hour.",
            "- Every request also computes the list's totals and the sidebar's option counts, "
            "because each run endpoint answers from one matching set.", "",
            "| Request | Cold | Warm p50 | Warm p95 | Maximum |",
            "| --- | ---: | ---: | ---: | ---: |",
            *table_rows(run_timings),
        ]
        rows += [
            "", "Target: ordinary interactive requests below 1,000 ms at this size.", "",
            "## Representative database plan", "",
            "The leading-wildcard shared search uses a sequential scan at this scale; total request time above "
            "also includes authorization, cost-line loading, aggregation, stable sorting, and serialization.",
            "", "```text", *plan, "```", "",
        ]
        args.output.write_text("\n".join(rows))
        session.rollback()
        print(args.output)


if __name__ == "__main__":
    main()
