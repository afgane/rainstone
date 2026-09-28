"""The Galaxy host VM and the start of its current running session.

The host is identified from the instance metadata server, or from an explicit
descriptor when the collector does not run on the Galaxy host. Metadata alone
only describes whatever machine the collector happens to run on, so it is
accepted only when its instance ID matches the configured Galaxy host.

One targeted Compute `instances.get`, made with the deployment's existing
metadata-issued credential, supplies the provider's `lastStartTimestamp`. That
is the start of the current running session; `creationTimestamp` describes the
VM's first creation and is never substituted for a later session. When the
start cannot be read, the observation says why and carries no launch time.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from rainstone.adapters.contracts import NormalizedServerObservation, ObservationBatch
from rainstone.adapters.gcp_batch import (
    CloudAccessDenied,
    GcpClient,
    catalog_purchase_model,
    provider_time,
)
from rainstone.discovery import HostMetadata

SOURCE_NAME = "galaxy_server"
LAUNCH_SOURCE = "compute.instances.get lastStartTimestamp"
STOPPED_STATES = {"STOPPED", "SUSPENDED", "TERMINATED"}


class HostUnconfirmed(RuntimeError):
    """The machine this collector can see is not known to be the Galaxy host."""


@dataclass(frozen=True)
class HostDescriptor:
    project: str
    zone: str
    instance_id: str
    source: str
    name: str | None = None
    machine_type: str | None = None
    purchase_model: str | None = None

    @property
    def region(self) -> str:
        return self.zone.rsplit("-", 1)[0]


def resolve_host(
    metadata: HostMetadata | None,
    *,
    expected_instance_id: str | None,
    project: str | None = None,
    zone: str | None = None,
) -> HostDescriptor:
    """The Galaxy host, from an explicit descriptor or from confirmed metadata."""
    if project and zone and expected_instance_id:
        return HostDescriptor(
            project=project, zone=zone, instance_id=expected_instance_id,
            source="configured descriptor",
        )
    if not expected_instance_id:
        raise HostUnconfirmed(
            "no Galaxy host instance ID is configured, so the machine this collector runs on "
            "is not assumed to be the Galaxy server"
        )
    if metadata is None:
        raise HostUnconfirmed("the host descriptor needs a project and zone without metadata")
    fields = metadata.descriptor()
    missing = [name for name in ("project", "instance_id", "zone") if not fields[name].ok]
    if missing:
        raise HostUnconfirmed(
            "instance metadata did not report " + ", ".join(missing) + "; "
            + fields[missing[0]].reason
        )
    instance_id = str(fields["instance_id"].value)
    if instance_id != expected_instance_id:
        raise HostUnconfirmed(
            f"this collector runs on instance {instance_id}, not the configured Galaxy host "
            f"{expected_instance_id}; a remote collector needs an explicit host descriptor"
        )

    def optional(name: str) -> str | None:
        return str(fields[name].value) if fields[name].ok else None

    return HostDescriptor(
        project=str(fields["project"].value),
        zone=str(fields["zone"].value),
        instance_id=instance_id,
        source="instance metadata",
        name=optional("node_name"),
        machine_type=optional("machine_type"),
        purchase_model=optional("purchase_model"),
    )


def _shape_conflict(host: HostDescriptor, machine_type: str | None, model: str | None) -> str | None:
    conflicts = [
        f"{label} is {described} in {host.source} but {observed} in the Compute API"
        for label, described, observed in (
            ("the machine type", host.machine_type, machine_type),
            ("the purchase model", host.purchase_model, model),
        )
        if described and observed and described != observed
    ]
    return "; ".join(conflicts) or None


def _ended_at(payload: dict, status: str | None, launch: datetime | None) -> datetime | None:
    if status not in STOPPED_STATES or launch is None:
        return None
    ends = [
        stamp for stamp in (
            provider_time(payload.get("lastStopTimestamp")),
            provider_time(payload.get("lastSuspendedTimestamp")),
        )
        if stamp is not None and stamp >= launch
    ]
    return max(ends, default=None)


def observe(
    host: HostDescriptor, client: GcpClient, observed_at: datetime
) -> NormalizedServerObservation:
    """Read the host's current session; a failed read explains itself."""
    base = {
        "provider": "gcp",
        "resource_uid": host.instance_id,
        "descriptor_source": host.source,
        "observed_at": observed_at,
        "name": host.name,
        "project": host.project,
        "zone": host.zone,
        "region": host.region,
        "machine_type": host.machine_type,
        "purchase_model": host.purchase_model,
    }
    try:
        payload = client.get_instance(host.project, host.zone, host.name or host.instance_id)
    except CloudAccessDenied as denial:
        return NormalizedServerObservation(
            **base,
            launch_unavailable_reason=(
                f"{denial.operation} was denied to this deployment's identity, so the start "
                "of the current session is unknown."
            ),
        )
    if payload is None:
        return NormalizedServerObservation(
            **base,
            launch_unavailable_reason=(
                f"The Compute API did not find instance {host.name or host.instance_id} in "
                f"{host.project}/{host.zone}, so the start of the current session is unknown."
            ),
        )
    if str(payload.get("id")) != host.instance_id:
        # A VM recreated under the same name has a different numeric ID; its
        # timestamps describe some other machine.
        return NormalizedServerObservation(
            **base,
            launch_unavailable_reason=(
                f"The Compute API describes instance {payload.get('id')}, not the Galaxy host "
                f"{host.instance_id}, so its start time is not used."
            ),
        )
    machine_type = (payload.get("machineType") or "").rsplit("/", 1)[-1] or None
    model = catalog_purchase_model((payload.get("scheduling") or {}).get("provisioningModel"))
    status = payload.get("status")
    launch = provider_time(payload.get("lastStartTimestamp"))
    return NormalizedServerObservation(
        **{
            **base,
            "name": payload.get("name") or host.name,
            "machine_type": machine_type or host.machine_type,
            "purchase_model": model or host.purchase_model,
        },
        state=status,
        launch_at=launch,
        launch_source=LAUNCH_SOURCE if launch else None,
        launch_unavailable_reason=None if launch else (
            "The Compute API reported no lastStartTimestamp for this instance, so the start of "
            "the current session is unknown."
        ),
        ended_at=_ended_at(payload, status, launch),
        shape_conflict=_shape_conflict(host, machine_type, model),
        facts={
            "status": status,
            "last_stop_timestamp": payload.get("lastStopTimestamp"),
        },
    )


class GalaxyServerCollector:
    """Observes the Galaxy host once per scheduled cycle."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        host: Callable[[], HostDescriptor],
        client: GcpClient,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._host = host
        self._client = client
        self._clock = clock

    def collect(self, cursor: dict) -> ObservationBatch:
        observed_at = self._clock()
        observation = observe(self._host(), self._client, observed_at)
        return ObservationBatch(
            source=SOURCE_NAME,
            observed_at=observed_at,
            servers=(observation,),
            metrics={
                "resource_uid": observation.resource_uid,
                "launch_known": observation.launch_at is not None,
            },
        )
