import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from rainstone import collector as module
from rainstone.acquisition import Delivery
from rainstone.adapters.contracts import NormalizedJob, ObservationBatch
from rainstone.adapters.gcp_batch import normalize_batch_job
from rainstone.collector import Collector, ScheduledSource, completed_batch_lifetimes
from rainstone.config import Settings
from rainstone.db import engine
from rainstone.ingestion import read_cursor, stable_id
from rainstone.models import CostLine, CostRevision, Job, ResourceLifetime, Tenant
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

STAMP = datetime(2026, 9, 22, tzinfo=UTC)


@pytest.fixture
def coordinator(tmp_path):
    slug = f"coordinator-{uuid.uuid4()}"
    tenant_id = stable_id("tenant", slug)
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, slug=slug, display_name="Coordinator", capabilities={}))
        session.commit()

    class Adapter:
        def __init__(self, name):
            self.source_name = name

    settings = Settings(tenant_slug=slug, auth_mode="development", demo_data=True,
                        diagnostics_enabled=False, catalog_feed_url=None,
                        collector_heartbeat_path=tmp_path / "heartbeat")
    process = Collector(settings, [ScheduledSource(Adapter(name), 30) for name in ("galaxy_db", "gcp_batch", "kubernetes")],
                        engine=engine)
    yield process
    with Session(engine) as session:
        session.execute(delete(Tenant).where(Tenant.id == tenant_id))
        session.commit()


def deliveries():
    job = NormalizedJob("336", "owner", "tool", "ok", STAMP, STAMP, runner="gcp_batch")
    payload = json.loads(Path("fixtures/contract/batch-job-retry.json").read_text())
    batch = ObservationBatch(source="gcp_batch", observed_at=STAMP,
                             attempts=tuple(normalize_batch_job(payload, payload["tasks"],
                                            project="demo-project", location="us-east4")), cursor={"offset": 1})
    return [Delivery("galaxy_db", 0, 1, payload=ObservationBatch(
        source="galaxy_db", observed_at=STAMP, jobs=(job,), cursor={"offset": 1})),
        Delivery("gcp_batch", 0, 1, payload=batch)]


def test_coordinator_coalesces_calculations_and_replay_does_not_duplicate_costs(coordinator, monkeypatch):
    calls = []
    calculate = module.calculate_tenant

    def counted(*args, **kwargs):
        calls.append(True)
        return calculate(*args, **kwargs)

    monkeypatch.setattr(module, "calculate_tenant", counted)
    coordinator.apply_deliveries(deliveries())
    assert len(calls) == 1
    with Session(engine) as session:
        before = session.scalar(select(func.count()).select_from(CostLine).join(Job, Job.id == CostLine.job_id).where(Job.tenant_id == coordinator.tenant_id))
        revision = session.get(CostRevision, coordinator.tenant_id).id
        assert read_cursor(session, coordinator.tenant_id, "gcp_batch") == {"offset": 1}
    coordinator.apply_deliveries(deliveries())
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CostLine).join(Job, Job.id == CostLine.job_id).where(Job.tenant_id == coordinator.tenant_id)) == before
        assert session.get(CostRevision, coordinator.tenant_id).id == revision
        assert session.scalar(select(func.count()).select_from(ResourceLifetime).where(ResourceLifetime.tenant_id == coordinator.tenant_id)) == 1


def test_calculation_failure_rolls_back_all_facts_and_cursors(coordinator, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("interrupted calculation")

    monkeypatch.setattr(module, "calculate_tenant", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        coordinator.apply_deliveries(deliveries())
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Job).where(Job.tenant_id == coordinator.tenant_id)) == 0
        assert read_cursor(session, coordinator.tenant_id, "galaxy_db") == {}
        assert read_cursor(session, coordinator.tenant_id, "gcp_batch") == {}


def test_heartbeat_remains_fresh_with_slow_worker_but_stalls_are_detected(coordinator, monkeypatch):
    blocked, release = threading.Event(), threading.Event()
    now = [0.0]
    coordinator._clock = lambda: now[0]
    coordinator._settings.collect_worker_stall_seconds = 450
    coordinator._sources = [item for item in coordinator._sources if item.adapter.source_name == "gcp_batch"]

    def collect(cursor):
        blocked.set()
        release.wait(3)
        return ObservationBatch(source="gcp_batch", observed_at=STAMP, cursor={})

    coordinator._sources[0].adapter.collect = collect
    monkeypatch.setattr(coordinator, "_acquire_catalog", lambda _: (None, None))
    coordinator.start_workers()
    try:
        assert blocked.wait(1)
        now[0] = 390
        coordinator.coordinate_once()
        heartbeat = coordinator._settings.collector_heartbeat_path
        assert heartbeat.exists()
        first = heartbeat.read_text()
        now[0] = 451
        coordinator.coordinate_once()
        assert heartbeat.read_text() == first
        assert "gcp_batch.worker" in coordinator._failures.states
    finally:
        for worker in coordinator._workers.values():
            worker.stop()
        release.set()
        for worker in coordinator._workers.values():
            worker.thread.join(1)


def test_only_complete_provider_lifetimes_are_reused(coordinator):
    from dataclasses import replace

    from rainstone.adapters.contracts import NormalizedAttempt, NormalizedLifetime
    from rainstone.ingestion import apply_batch
    from rainstone.models import CapacityRelationship

    coordinator.apply_deliveries(deliveries())
    with Session(engine) as session:
        lifetime = session.scalar(select(ResourceLifetime).where(ResourceLifetime.tenant_id == coordinator.tenant_id))
        lifetime.timing_method = "compute_instance_timestamps"
        lifetime.observed_start = STAMP
        lifetime.observed_end = None
        session.commit()
        assert not completed_batch_lifetimes(session, coordinator.tenant_id, ["336"])
        fallback = NormalizedLifetime(provider="gcp", resource_key=lifetime.resource_key,
                                      resource_uid=lifetime.resource_uid, capacity_relationship=CapacityRelationship.dedicated,
                                      timing_method="batch_task_events", observed_start=STAMP, observed_end=STAMP)
        attempt = NormalizedAttempt("336", "fallback", "gcp_batch", "succeeded", lifetimes=(fallback,))
        apply_batch(session, coordinator.tenant_id, ObservationBatch(source="gcp_batch", observed_at=STAMP, attempts=(attempt,)))
        session.commit()
        assert not completed_batch_lifetimes(session, coordinator.tenant_id, ["336"])
        audit = replace(fallback, timing_method="compute_insert_complete_to_delete_request",
                        observed_end=STAMP.replace(hour=1), facts={"missing_provisioning_overhead": False})
        apply_batch(session, coordinator.tenant_id, ObservationBatch(source="gcp_batch", observed_at=STAMP.replace(hour=1),
                                                                    attempts=(replace(attempt, lifetimes=(audit,)),)))
        session.commit()
        assert not completed_batch_lifetimes(session, coordinator.tenant_id, ["other"])
        complete = completed_batch_lifetimes(session, coordinator.tenant_id, ["336"])["336"]
        assert len(complete) == 1
        assert complete[0].observed_end == STAMP.replace(hour=1)


def test_catalog_delivery_preserves_operation_name_and_uses_the_same_writer(coordinator):
    from rainstone.catalog import load_file

    artifact = load_file(Path("fixtures/price-catalog-pilot.json"))
    results = coordinator.apply_deliveries([
        *deliveries(), Delivery("price_catalog", 0, 1, payload=(artifact, None)),
    ])
    assert results[-1]["source"] == "price_catalog"
    assert results[-1]["status"] == "refreshed"
    with Session(engine) as session:
        assert session.get(CostRevision, coordinator.tenant_id) is not None


def test_queue_summary_reports_backpressure_without_exposing_payloads(coordinator):
    coordinator._clock = lambda: 10
    coordinator._queue.put(Delivery("kubernetes", 1, 3, payload={"private": "hidden"}))
    assert coordinator.queue_metrics() == {
        "queue_depth": 1, "queue_capacity": 64, "oldest_queued_seconds": 7,
    }


def test_failed_snapshot_does_not_commit_later_queued_batches(coordinator, monkeypatch):
    coordinator._sources = [item for item in coordinator._sources if item.adapter.source_name == "kubernetes"]
    later = Delivery("kubernetes", 0, 1, payload=ObservationBatch(
        source="kubernetes", observed_at=STAMP, cursor={"resource_version": "2"}))

    calculate = module.calculate_tenant
    calls = []

    def fail_once(*args, **kwargs):
        calls.append(True)
        if len(calls) > 1:
            return calculate(*args, **kwargs)
        coordinator._queue.put(later)
        raise RuntimeError("interrupted calculation")

    monkeypatch.setattr(module, "calculate_tenant", fail_once)
    coordinator._queue.put(Delivery("kubernetes", 0, 1, payload=ObservationBatch(
        source="kubernetes", observed_at=STAMP, cursor={"resource_version": "1"})))
    monkeypatch.setattr(coordinator, "start_workers", lambda: None)
    with pytest.raises(RuntimeError, match="interrupted"):
        coordinator.run_forever()
    with Session(engine) as session:
        assert read_cursor(session, coordinator.tenant_id, "kubernetes") == {}


def test_clean_stop_applies_queued_batches(coordinator, monkeypatch):
    coordinator._sources = [item for item in coordinator._sources if item.adapter.source_name == "kubernetes"]
    monkeypatch.setattr(coordinator, "start_workers", lambda: None)
    coordinator._queue.put(Delivery("kubernetes", 0, 1, payload=ObservationBatch(
        source="kubernetes", observed_at=STAMP, cursor={"resource_version": "1"})))
    coordinator.run_forever(lambda: True)
    with Session(engine) as session:
        assert read_cursor(session, coordinator.tenant_id, "kubernetes") == {"resource_version": "1"}


def test_transform_failure_is_a_source_failure_not_a_lost_snapshot(coordinator):
    def collect(cursor):
        return ObservationBatch(source="galaxy_db", observed_at=STAMP, cursor={"offset": 1})

    def transform(batch):
        raise RuntimeError("baseline profile unavailable")

    source = next(item for item in coordinator._sources if item.adapter.source_name == "galaxy_db")
    source.adapter.collect = collect
    source.transform = transform
    coordinator._queue.put(deliveries()[1])
    results = coordinator.coordinate_once()
    assert {result["source"]: result.get("status") for result in results}["galaxy_db"] == "failed"
    assert source.due_at > 0
    with Session(engine) as session:
        assert read_cursor(session, coordinator.tenant_id, "galaxy_db") == {}
        assert read_cursor(session, coordinator.tenant_id, "gcp_batch") == {"offset": 1}


def test_worker_failures_report_the_worker_retry_delay(coordinator):
    coordinator._clock = lambda: 100
    source = next(item for item in coordinator._sources if item.adapter.source_name == "gcp_batch")
    results = coordinator.apply_deliveries([
        Delivery("gcp_batch", 0, 1, error=RuntimeError("temporary"), retry_seconds=42),
    ])
    assert results[0]["retry_in_seconds"] == 42
    assert source.failures == 0
    assert source.due_at == 0
