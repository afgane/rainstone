"""The Galaxy server's hourly rate and total since its current launch.

Observations are injected with a fixed clock; no cloud instance is needed.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rainstone.adapters.galaxy_server import GalaxyServerCollector, HostDescriptor
from rainstone.adapters.gcp_batch import CloudAccessDenied
from rainstone.auth import Identity
from rainstone.collector import Collector, ScheduledSource
from rainstone.config import Settings
from rainstone.costing import current_generation
from rainstone.db import engine
from rainstone.ingestion import stable_id
from rainstone.models import (
    GalaxyServerSession,
    IngestionEvent,
    IngestionState,
    PriceVersion,
    Tenant,
)
from rainstone.reporting import current_launch
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .conftest import headers

SLUG = "galaxy-server-test"
TENANT_ID = stable_id("tenant", SLUG)
LAUNCH = datetime(2026, 9, 25, 6, tzinfo=UTC)
HOST = HostDescriptor(
    project="server-project", zone="us-test1-a", instance_id="4242",
    source="instance metadata", name="galaxy-host", machine_type="t2d-test-4",
    purchase_model="on_demand",
)
IDENTITY = Identity(
    TENANT_ID, uuid.uuid4(), "admin", "admin", True, can_view_infrastructure=True
)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class Compute:
    def __init__(self, launch: datetime = LAUNCH, machine: str = "t2d-test-4") -> None:
        self.launch = launch
        self.machine = machine
        self.denied = False

    def get_instance(self, project: str, zone: str, instance_id: str) -> dict:
        if self.denied:
            raise CloudAccessDenied("compute.instances.get")
        return {
            "id": "4242", "name": "galaxy-host", "status": "RUNNING",
            "machineType": f"zones/{zone}/machineTypes/{self.machine}",
            "scheduling": {"provisioningModel": "STANDARD"},
            "creationTimestamp": "2026-01-01T00:00:00Z",
            "lastStartTimestamp": self.launch.isoformat(),
        }


@pytest.fixture()
def server_tenant():
    with Session(engine) as session:
        session.add(Tenant(id=TENANT_ID, slug=SLUG, display_name="Server test", capabilities={}))
        session.add(PriceVersion(
            id=uuid.uuid4(), catalog_id="galaxy-server-test", machine_type="t2d-test-4",
            provider="gcp", region="us-test1", purchase_model="on_demand", currency="USD",
            hourly_rate=Decimal("0.20"), observed_at=LAUNCH, effective_from=None,
            provenance={"kind": "test"},
        ))
        session.commit()
    yield
    with Session(engine) as session:
        session.execute(delete(PriceVersion).where(PriceVersion.catalog_id == "galaxy-server-test"))
        session.execute(delete(Tenant).where(Tenant.id == TENANT_ID))
        session.commit()


def collector(clock: Clock, compute: Compute) -> tuple[Collector, ScheduledSource]:
    """A freshly started collector process, as after a pod restart."""
    source = ScheduledSource(
        adapter=GalaxyServerCollector(lambda: HOST, compute, clock=clock), interval_seconds=60
    )
    settings = Settings(auth_mode="development", demo_data=True, tenant_slug=SLUG)
    return Collector(settings, [source], engine=engine), source


def poll(clock: Clock, compute: Compute, at: datetime) -> dict:
    clock.now = at
    process, source = collector(clock, compute)
    process.collect_source(source)
    return report(at)


def report(now: datetime) -> dict:
    with Session(engine) as session:
        return current_launch(session, IDENTITY, now=now)


def generation() -> int:
    with Session(engine) as session:
        return current_generation(session, TENANT_ID)


def test_three_hours_after_launch_costs_sixty_cents_without_jobs(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    # Rainstone was installed long after the launch; the provider's start still counts.
    poll(clock, compute, LAUNCH + timedelta(hours=2, minutes=55))
    result = poll(clock, compute, LAUNCH + timedelta(hours=3))

    assert Decimal(result["total_since_launch"]) == Decimal("0.60")
    assert Decimal(result["hourly_rate"]) == Decimal("0.20")
    assert result["completeness"] == "complete"
    assert result["launch_at"] == LAUNCH.isoformat()
    assert result["launch_source"] == "compute.instances.get lastStartTimestamp"
    assert result["as_of"] == (LAUNCH + timedelta(hours=3)).isoformat()
    assert result["stale"] is False
    assert result["price"]["catalog_id"] == "galaxy-server-test"
    # This test-only shape has no published capacity; do not infer it from its name.
    assert result["machine_capacity"] is None


def test_repeated_polls_and_restarts_neither_reset_nor_double_count(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    poll(clock, compute, LAUNCH + timedelta(hours=1))
    after_first = generation()
    for minute in range(1, 6):
        result = poll(clock, compute, LAUNCH + timedelta(hours=1, minutes=minute))

    one_hour_five_minutes = Decimal("0.20") * 65 / 60
    assert Decimal(result["total_since_launch"]).quantize(Decimal("1e-12")) == (
        one_hour_five_minutes.quantize(Decimal("1e-12"))
    )
    assert result["launch_at"] == LAUNCH.isoformat()
    # Heartbeats are not new facts, so pinned reports are not invalidated each minute.
    assert generation() == after_first
    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(GalaxyServerSession)
            .where(GalaxyServerSession.tenant_id == TENANT_ID)
        ) == 1
        row = session.scalar(select(GalaxyServerSession).where(GalaxyServerSession.tenant_id == TENANT_ID))
        assert row.first_observed_at == LAUNCH + timedelta(hours=1)
        # One event per distinct state, not one per poll.
        assert session.scalar(
            select(func.count()).select_from(IngestionEvent).where(
                IngestionEvent.tenant_id == TENANT_ID, IngestionEvent.source == "galaxy_server"
            )
        ) == 1


def test_a_new_start_begins_a_fresh_total_with_nothing_carried_over(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    poll(clock, compute, LAUNCH + timedelta(hours=3))
    before = generation()

    compute.launch = LAUNCH + timedelta(hours=5)
    result = poll(clock, compute, LAUNCH + timedelta(hours=6))

    assert Decimal(result["total_since_launch"]) == Decimal("0.20")
    assert result["launch_at"] == compute.launch.isoformat()
    assert generation() > before


def test_a_failed_read_freezes_the_known_session_and_marks_it_stale(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    poll(clock, compute, LAUNCH + timedelta(hours=3))

    compute.denied = True
    later = LAUNCH + timedelta(hours=4)
    result = poll(clock, compute, later)

    # The total stops at the last successful observation instead of accruing.
    assert Decimal(result["total_since_launch"]) == Decimal("0.60")
    assert result["as_of"] == (LAUNCH + timedelta(hours=3)).isoformat()
    assert result["stale"] is True
    assert "last observed 60 minutes ago" in result["stale_reason"]
    with Session(engine) as session:
        state = session.scalar(select(IngestionState).where(
            IngestionState.tenant_id == TENANT_ID, IngestionState.source == "galaxy_server"
        ))
        assert state.status == "degraded"
        assert "compute.instances.get was denied" in state.error


def test_an_unknown_start_shows_the_rate_but_no_fabricated_total(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    compute.denied = True
    result = poll(clock, compute, LAUNCH + timedelta(hours=1))

    assert Decimal(result["hourly_rate"]) == Decimal("0.20")
    assert result["launch_at"] is None
    assert result["total_since_launch"] is None
    assert result["completeness"] == "unavailable"
    assert "denied" in result["unavailable_reason"]


def test_contradicting_shape_evidence_makes_the_total_unavailable(server_tenant) -> None:
    clock, compute = Clock(LAUNCH), Compute()
    poll(clock, compute, LAUNCH + timedelta(hours=1))
    compute.machine = "t2d-test-8"
    result = poll(clock, compute, LAUNCH + timedelta(hours=2))

    assert result["total_since_launch"] is None
    assert result["hourly_rate"] is None
    assert "t2d-test-4" in result["unavailable_reason"]
    assert "t2d-test-8" in result["unavailable_reason"]


def test_no_observation_is_explained_rather_than_shown_as_free(server_tenant) -> None:
    result = report(LAUNCH)

    assert result["total_since_launch"] is None
    assert result["hourly_rate"] is None
    assert "No observation of the Galaxy server" in result["unavailable_reason"]


def test_report_filters_and_timezone_leave_the_server_figures_unchanged(client) -> None:
    auth = headers("admin", True)
    queries = (
        "", "?owner=alice", "?tool_id=cat1", "?from=2026-09-19T00:00:00Z&to=2026-09-19T12:00:00Z",
        "?runner=gcp_batch", "?basis=allocated", "?mode=completed", "?timezone=Pacific/Auckland",
        "?search=nothing-matches-this",
    )
    results = []
    for query in queries:
        summary = client.get(f"/api/summary{query}", headers=auth)
        infrastructure = client.get(f"/api/infrastructure{query}", headers=auth)
        assert summary.status_code == infrastructure.status_code == 200
        launch = summary.json()["current_launch"]
        assert launch == infrastructure.json()["current_launch"]
        results.append(launch)
    assert all(result == results[0] for result in results)

    demo = results[0]
    # The demonstration server ran three hours; other tests may import catalogs
    # that reprice it, so only its shape and duration are fixed here.
    assert Decimal(demo["elapsed_seconds"]) == Decimal("10800")
    assert demo["completeness"] == "complete"
    assert demo["machine_type"] == "t2d-standard-4"
    assert demo["machine_capacity"] == {
        "vcpu": "4", "memory_mib": "16384", "gpu": None, "source": "published_machine_shape",
    }
    assert demo["stale"] is True


def test_server_figures_follow_infrastructure_authorization(client) -> None:
    assert client.get("/api/summary", headers=headers("alice")).json()["current_launch"] is None
    assert client.get("/api/infrastructure", headers=headers("alice")).status_code == 403
