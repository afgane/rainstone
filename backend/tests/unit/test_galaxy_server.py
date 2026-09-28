import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from rainstone.adapters.galaxy_server import (
    LAUNCH_SOURCE,
    GalaxyServerCollector,
    HostDescriptor,
    HostUnconfirmed,
    observe,
    resolve_host,
)
from rainstone.adapters.gcp_batch import CloudAccessDenied
from rainstone.costing import calculate_server_session
from rainstone.discovery import HostMetadata
from rainstone.models import GalaxyServerSession, PriceVersion

LAUNCH = datetime(2026, 9, 25, 9, tzinfo=UTC)
METADATA = {
    "project/project-id": "anvil-project",
    "instance/id": "8649021727128195799",
    "instance/name": "galaxy-host",
    "instance/machine-type": "projects/1/machineTypes/t2d-standard-4",
    "instance/zone": "projects/1/zones/us-central1-a",
    "instance/scheduling/preemptible": "FALSE",
}
HOST = HostDescriptor(
    project="anvil-project", zone="us-central1-a", instance_id="8649021727128195799",
    source="instance metadata", name="galaxy-host", machine_type="t2d-standard-4",
    purchase_model="on_demand",
)


class FakeMetadata(HostMetadata):
    def __init__(self, values: dict | None) -> None:
        self.values = values

    def _read(self, path: str) -> str | None:
        return (self.values or {}).get(path)


class FakeCompute:
    def __init__(self, payload: dict | None = None, denied: bool = False) -> None:
        self.payload = payload
        self.denied = denied
        self.requests: list[tuple[str, str, str]] = []

    def get_instance(self, project: str, zone: str, instance_id: str) -> dict | None:
        self.requests.append((project, zone, instance_id))
        if self.denied:
            raise CloudAccessDenied("compute.instances.get", "Forbidden")
        return self.payload


def instance(**changes) -> dict:
    return {
        "id": "8649021727128195799",
        "name": "galaxy-host",
        "status": "RUNNING",
        "machineType": "https://compute.googleapis.com/compute/v1/projects/p/zones/z/machineTypes/t2d-standard-4",
        "scheduling": {"provisioningModel": "STANDARD"},
        "creationTimestamp": "2026-08-01T12:00:00.000-07:00",
        "lastStartTimestamp": "2026-09-25T02:00:00.123456789-07:00",
        "lastStopTimestamp": "2026-09-24T18:00:00.000-07:00",
        **changes,
    }


def test_metadata_describes_the_galaxy_host_only_when_its_id_matches() -> None:
    host = resolve_host(FakeMetadata(METADATA), expected_instance_id="8649021727128195799")
    assert host == HOST
    assert host.region == "us-central1"

    with pytest.raises(HostUnconfirmed, match="not the configured Galaxy host"):
        resolve_host(FakeMetadata(METADATA), expected_instance_id="42")
    with pytest.raises(HostUnconfirmed, match="not assumed"):
        resolve_host(FakeMetadata(METADATA), expected_instance_id=None)
    with pytest.raises(HostUnconfirmed, match="did not report"):
        resolve_host(FakeMetadata(None), expected_instance_id="8649021727128195799")


def test_a_remote_collector_uses_its_explicit_descriptor_not_its_own_machine() -> None:
    host = resolve_host(
        FakeMetadata({**METADATA, "instance/id": "1"}),
        expected_instance_id="8649021727128195799",
        project="anvil-project",
        zone="us-central1-a",
    )
    assert host.source == "configured descriptor"
    assert host.instance_id == "8649021727128195799"


def test_the_current_session_starts_at_the_providers_last_start() -> None:
    compute = FakeCompute(instance())
    observed = observe(HOST, compute, LAUNCH)

    # A restart after a stop is a new session; the VM's creation is not its start.
    assert observed.launch_at == datetime(2026, 9, 25, 9, 0, 0, 123456, tzinfo=UTC)
    assert observed.launch_source == LAUNCH_SOURCE
    assert observed.machine_type == "t2d-standard-4"
    assert observed.purchase_model == "on_demand"
    assert observed.ended_at is None
    assert observed.shape_conflict is None
    assert observed.session_key.endswith("8649021727128195799@2026-09-25T09:00:00.123456+00:00")
    assert compute.requests == [("anvil-project", "us-central1-a", "galaxy-host")]


def test_a_missing_start_is_explained_and_never_replaced_by_creation_time() -> None:
    payload = instance()
    del payload["lastStartTimestamp"]
    observed = observe(HOST, FakeCompute(payload), LAUNCH)

    assert observed.launch_at is None
    assert observed.session_key is None
    assert "no lastStartTimestamp" in observed.launch_unavailable_reason
    # The shape is still known, so the hourly rate can be shown.
    assert observed.machine_type == "t2d-standard-4"


def test_a_denied_read_keeps_the_host_shape_and_says_what_was_denied() -> None:
    observed = observe(HOST, FakeCompute(denied=True), LAUNCH)

    assert observed.launch_at is None
    assert "compute.instances.get was denied" in observed.launch_unavailable_reason
    assert observed.machine_type == "t2d-standard-4"


def test_a_different_vm_under_the_same_name_is_not_used() -> None:
    observed = observe(HOST, FakeCompute(instance(id="99")), LAUNCH)

    assert observed.launch_at is None
    assert "not the Galaxy host" in observed.launch_unavailable_reason


def test_contradictory_shape_evidence_is_reported() -> None:
    observed = observe(HOST, FakeCompute(instance(machineType="zones/z/machineTypes/n2-standard-8")), LAUNCH)

    assert "t2d-standard-4 in instance metadata but n2-standard-8" in observed.shape_conflict


def test_a_stopped_session_ends_at_the_providers_stop_time() -> None:
    observed = observe(
        HOST,
        FakeCompute(instance(status="TERMINATED", lastStopTimestamp="2026-09-25T12:00:00Z")),
        LAUNCH,
    )

    assert observed.ended_at == datetime(2026, 9, 25, 12, tzinfo=UTC)


def test_the_collector_emits_one_server_observation_per_cycle() -> None:
    collector = GalaxyServerCollector(lambda: HOST, FakeCompute(instance()), clock=lambda: LAUNCH)
    batch = collector.collect({})

    assert batch.source == "galaxy_server"
    assert len(batch.servers) == 1
    assert batch.jobs == () and batch.attempts == ()


def price(rate: str, effective_from: datetime | None = None, catalog: str = "c1") -> PriceVersion:
    return PriceVersion(
        id=uuid.uuid4(), catalog_id=catalog, machine_type="t2d-standard-4", provider="gcp",
        region="us-central1", purchase_model="on_demand", currency="USD",
        hourly_rate=Decimal(rate), observed_at=LAUNCH, effective_from=effective_from,
        provenance={"kind": "test"},
    )


def server(seconds: float, **changes) -> GalaxyServerSession:
    values = {
        "provider": "gcp", "resource_uid": "1", "project": "p", "zone": "us-central1-a",
        "region": "us-central1", "machine_type": "t2d-standard-4", "purchase_model": "on_demand",
        "state": "RUNNING", "descriptor_source": "test", "launch_at": LAUNCH,
        "session_key": "k", "first_observed_at": LAUNCH + timedelta(seconds=seconds),
        "observed_at": LAUNCH + timedelta(seconds=seconds), "ended_at": None,
        "shape_conflict": None, "launch_unavailable_reason": None, "facts": {},
    }
    return GalaxyServerSession(**{**values, **changes})


def test_three_hours_at_twenty_cents_is_sixty_cents() -> None:
    cost = calculate_server_session(server(3 * 3600), [price("0.20")])

    assert cost.completeness == "complete"
    assert cost.total == Decimal("0.60")
    assert cost.rate.hourly_rate == Decimal("0.20")
    assert cost.cutoff == LAUNCH + timedelta(hours=3)


def test_the_provider_minimum_applies_once_to_the_session() -> None:
    cent = Decimal("0.000001")
    short = calculate_server_session(server(30), [price("0.60")])
    assert short.billed_seconds == Decimal("60")
    assert short.total.quantize(cent) == Decimal("0.01")
    assert calculate_server_session(server(120), [price("0.60")]).total.quantize(cent) == Decimal("0.02")


def test_a_price_change_inside_the_session_splits_it() -> None:
    change = LAUNCH + timedelta(hours=1)
    cost = calculate_server_session(
        server(3 * 3600), [price("0.20"), price("0.50", change, catalog="c2")]
    )

    assert cost.total == Decimal("0.20") + Decimal("1.00")
    assert [allocation["hourly_rate"] for allocation in cost.allocations] == ["0.20", "0.50"]
    assert cost.rate.hourly_rate == Decimal("0.50")


def test_time_before_the_earliest_price_leaves_a_labeled_subtotal() -> None:
    later = LAUNCH + timedelta(hours=2)
    cost = calculate_server_session(server(3 * 3600), [price("0.20", later)])

    assert cost.completeness == "partial"
    assert cost.total is None
    assert cost.known_subtotal == Decimal("0.20")
    assert "never applied to earlier time" in cost.unavailable_reason


def test_an_unpriced_shape_has_neither_rate_nor_total() -> None:
    cost = calculate_server_session(server(3600, machine_type="e2-medium"), [])

    assert cost.completeness == "unavailable"
    assert cost.rate is None
    assert "no rate for e2-medium" in cost.rate_unavailable_reason
    assert cost.total is None


def test_an_unknown_launch_keeps_the_rate_but_not_the_total() -> None:
    cost = calculate_server_session(
        server(3600, launch_at=None, session_key=None, launch_unavailable_reason="denied"),
        [price("0.20")],
    )

    assert cost.rate.hourly_rate == Decimal("0.20")
    assert cost.completeness == "unavailable"
    assert cost.unavailable_reason == "denied"


def test_contradicted_shape_makes_the_total_unavailable() -> None:
    cost = calculate_server_session(
        server(3600, shape_conflict="the machine type was a but is now b"), [price("0.20")]
    )

    assert cost.completeness == "unavailable"
    assert cost.total is None
    assert "contradicted" in cost.unavailable_reason


def test_a_stopped_session_is_priced_only_until_it_stopped() -> None:
    stopped = server(
        5 * 3600, state="TERMINATED", ended_at=LAUNCH + timedelta(hours=2)
    )
    assert calculate_server_session(stopped, [price("0.20")]).total == Decimal("0.40")

    unknown_stop = server(5 * 3600, state="TERMINATED")
    cost = calculate_server_session(unknown_stop, [price("0.20")])
    assert cost.completeness == "unavailable"
    assert "did not report when" in cost.unavailable_reason
