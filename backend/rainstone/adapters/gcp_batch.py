"""GCP Batch, Compute and Logging observation.

Galaxy stores only a short Batch job name, so every read combines it with the
configured project and location and keeps the full resolved resource name and
UID. Provider retries appear in *task* status events, not in the top-level job
status, and a retry can reuse the same VM: the same-VM retry captured for CI job
336 is the reference case. Each distinct VM becomes one chargeable lifetime that
several attempts may share.

Instance identities parsed out of task-event descriptions are labeled as
text-parsed correlation hints, because that text is not a stable structured
field. Live Compute reads and Logging operation boundaries are preferred when
available.
"""

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from rainstone.adapters.contracts import (
    NormalizedAttempt,
    NormalizedGap,
    NormalizedLifetime,
    NormalizedSegment,
    ObservationBatch,
)
from rainstone.models import CapacityRelationship

logger = logging.getLogger("rainstone.adapters.gcp_batch")

SOURCE_NAME = "gcp_batch"
JOB_LABEL = "galaxy-job-id"
METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)
INSTANCE_REFERENCE = re.compile(r"zones/(?P<zone>[a-z0-9-]+)/instances/(?P<instance>\d+)")


class CloudAccessDenied(RuntimeError):
    """The deployment's identity lacks a permission this observation needs.

    Denied is not the same as absent: a missing resource is a normal answer,
    while a denial is a capability gap an operator must see.
    """

    def __init__(self, operation: str, detail: str = "") -> None:
        super().__init__(f"{operation} was denied{': ' + detail if detail else ''}")
        self.operation = operation
ATTEMPT_REFERENCE = re.compile(r"Attempt (?P<ordinal>\d+) failed")


def catalog_purchase_model(value: str | None) -> str | None:
    """Translate the provider's provisioning model into catalog vocabulary.

    Batch reports how a VM was provisioned (`STANDARD`, `SPOT`); a price
    catalog names how it is charged (`on_demand`, `spot`). They describe the
    same thing in different words, and a lifetime whose words do not match the
    catalog's silently fails to price. A model this mapping does not know stays
    as the provider wrote it, so it reads as unpriced rather than being charged
    at an on-demand rate it may not deserve.
    """
    normalized = (value or "").strip().lower()
    if not normalized:
        return None
    return {"standard": "on_demand", "preemptible": "spot"}.get(normalized, normalized)


def provider_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    # Provider timestamps carry nanosecond precision; Python parses microseconds.
    match = re.match(r"(.*\.\d{6})\d*(?P<offset>[+-]\d{2}:\d{2})$", text)
    if match:
        text = f"{match.group(1)}{match.group('offset')}"
    return datetime.fromisoformat(text).astimezone(UTC)


@dataclass(frozen=True)
class BatchTarget:
    """One Galaxy job whose Batch resource should be observed."""

    job_source_id: str
    external_id: str
    project: str
    location: str
    active: bool = False
    completed_lifetimes: tuple[NormalizedLifetime, ...] = ()


@dataclass(frozen=True)
class InstanceObservation:
    instance_id: str
    zone: str
    project: str
    created_at: datetime | None = None
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    machine_type: str | None = None
    purchase_model: str | None = None
    labels: dict = field(default_factory=dict)
    source: str = "compute_instance"


class GcpClient(Protocol):
    # Monotonic time after which requests raise CollectionBudgetExpired.
    deadline: float | None
    request_metrics: dict[str, dict]

    def get_batch_job(self, project: str, location: str, job_id: str) -> dict | None: ...

    def list_batch_tasks(self, job_name: str, group: str = "group0") -> list[dict]: ...

    def get_instance(self, project: str, zone: str, instance_id: str) -> dict | None: ...

    def instance_lifecycle_entries(
        self, project: str, instance_id: str, *, after: datetime | None = None, before: datetime | None = None
    ) -> list[dict]: ...

    def probe_access(self, project: str, location: str) -> dict[str, str]: ...


class HttpGcpClient:
    """REST access using the deployment's own runtime identity.

    The access token comes from VM or workload metadata; a developer `gcloud`
    session is never used, and no token value is logged or persisted.
    """

    def __init__(self, *, token_provider: Callable[[], str] | None = None, page_limit: int = 100):
        self._token_provider = token_provider or self._metadata_token
        self._page_limit = page_limit
        self.deadline: float | None = None
        self.request_metrics: dict[str, dict] = {}

    @staticmethod
    def _metadata_token() -> str:
        request = urllib.request.Request(
            METADATA_TOKEN_URL, headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return json.load(response)["access_token"]

    def _request(self, url: str, params: dict | None = None, *, payload: dict | None = None,
                 operation: str = "read") -> dict | None:
        started = time.monotonic()
        try:
            remaining = self.deadline - started if self.deadline is not None else 30
            if remaining <= 0:
                raise CollectionBudgetExpired()
            if params:
                url = f"{url}?{urllib.parse.urlencode(params)}"
            token = self._token_provider()
            remaining = self.deadline - time.monotonic() if self.deadline is not None else 30
            if remaining <= 0:
                raise CollectionBudgetExpired()
            request = urllib.request.Request(
                url, data=json.dumps(payload).encode() if payload is not None else None,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=min(30, remaining)) as response:  # noqa: S310
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in {401, 403}:
                raise CloudAccessDenied(operation, error.reason or "") from error
            if error.code == 404:
                return None
            raise
        except (TimeoutError, urllib.error.URLError) as error:
            if self.deadline is not None and time.monotonic() >= self.deadline:
                raise CollectionBudgetExpired() from error
            raise
        finally:
            elapsed = round((time.monotonic() - started) * 1000, 1)
            metric = self.request_metrics.setdefault(operation, {"count": 0, "total_ms": 0.0})
            metric["count"] += 1
            metric["total_ms"] = round(metric["total_ms"] + elapsed, 1)
            logger.debug("provider_request_completed", extra={"fields": {
                "source": SOURCE_NAME, "operation": operation, "duration_ms": elapsed,
            }})

    def _get(self, url: str, params: dict | None = None, *, operation: str = "read") -> dict | None:
        return self._request(url, params, operation=operation)

    def _post(self, url: str, payload: dict, *, operation: str = "read") -> dict | None:
        return self._request(url, payload=payload, operation=operation)

    def get_batch_job(self, project: str, location: str, job_id: str) -> dict | None:
        return self._get(
            "https://batch.googleapis.com/v1/"
            f"projects/{project}/locations/{location}/jobs/{job_id}",
            operation="batch.jobs.get",
        )

    def list_batch_tasks(self, job_name: str, group: str = "group0") -> list[dict]:
        tasks: list[dict] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"pageSize": self._page_limit}
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(
                f"https://batch.googleapis.com/v1/{job_name}/taskGroups/{group}/tasks",
                params,
                operation="batch.tasks.list",
            )
            if not payload:
                return tasks
            tasks.extend(payload.get("tasks", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return tasks

    def list_batch_instances(self, project: str, job_id: str, uid: str | None = None) -> list[dict]:
        """Verify cleanup by provider labels, including VMs not yet in task events."""
        result = []
        page_token = None
        while True:
            params = {"filter": f'labels.batch-job-uid = "{uid}"' if uid else f'labels.batch-job-id = "{job_id}"',
                      "returnPartialSuccess": "true"}
            if page_token:
                params["pageToken"] = page_token
            payload = self._get(f"https://compute.googleapis.com/compute/v1/projects/{project}/aggregated/instances",
                                params, operation="compute.instances.list")
            if payload is None or payload.get("warning", {}).get("code") not in {None, "NO_RESULTS_ON_PAGE"}:
                raise CloudAccessDenied("compute.instances.list", "Complete inventory unavailable")
            for group in payload.get("items", {}).values():
                warning = group.get("warning", {}).get("code")
                if warning and warning != "NO_RESULTS_ON_PAGE":
                    raise CloudAccessDenied("compute.instances.list", "Incomplete zone inventory")
                result.extend(group.get("instances", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return result

    def get_instance(self, project: str, zone: str, instance_id: str) -> dict | None:
        return self._get(
            "https://compute.googleapis.com/compute/v1/"
            f"projects/{project}/zones/{zone}/instances/{instance_id}",
            operation="compute.instances.get",
        )

    def instance_lifecycle_entries(
        self, project: str, instance_id: str, *, after: datetime | None = None, before: datetime | None = None
    ) -> list[dict]:
        window = (
            f' AND timestamp>="{after.isoformat()}"' if after else ""
        )
        if before:
            window += f' AND timestamp<="{before.isoformat()}"'
        query = (
            f'resource.type="gce_instance" AND resource.labels.instance_id="{instance_id}"'
            ' AND (protoPayload.methodName="v1.compute.instances.insert"'
            ' OR protoPayload.methodName="v1.compute.instances.delete")'
            f"{window}"
        )
        entries: list[dict] = []
        page_token: str | None = None
        while True:
            payload = self._post(
                "https://logging.googleapis.com/v2/entries:list",
                operation="logging.logEntries.list",
                payload={
                    "resourceNames": [f"projects/{project}"],
                    "filter": query,
                    "orderBy": "timestamp asc",
                    "pageSize": self._page_limit,
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            if not payload:
                return entries
            entries.extend(payload.get("entries", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                return entries


    def probe_access(self, project: str, location: str) -> dict[str, str]:
        """Exercise the operations each enabled observation actually needs.

        A probe reports `ok`, `denied` or `unavailable`; a missing resource is
        `ok`, because absence is a valid answer from an API that answered.
        """
        # Every operation collection performs is probed, not only the listings:
        # list permission does not imply get, and a missing resource answers
        # 404, which is a permitted call rather than a denial.
        missing = "rainstone-capability-probe"
        probes = {
            "batch.jobs.list": (
                self._get,
                (
                    "https://batch.googleapis.com/v1/"
                    f"projects/{project}/locations/{location}/jobs",
                    {"pageSize": 1},
                ),
            ),
            "batch.jobs.get": (
                self._get,
                (
                    "https://batch.googleapis.com/v1/"
                    f"projects/{project}/locations/{location}/jobs/{missing}",
                    None,
                ),
            ),
            "batch.tasks.list": (
                self._get,
                (
                    "https://batch.googleapis.com/v1/"
                    f"projects/{project}/locations/{location}/jobs/{missing}"
                    "/taskGroups/group0/tasks",
                    {"pageSize": 1},
                ),
            ),
            "compute.instances.get": (
                self._get,
                (
                    "https://compute.googleapis.com/compute/v1/"
                    f"projects/{project}/zones/{location}-a/instances/{missing}",
                    None,
                ),
            ),
            "compute.instances.list": (
                self._get,
                (
                    "https://compute.googleapis.com/compute/v1/"
                    f"projects/{project}/aggregated/instances",
                    {"maxResults": 1},
                ),
            ),
            "logging.logEntries.list": (
                self._post,
                (
                    "https://logging.googleapis.com/v2/entries:list",
                    {
                        "resourceNames": [f"projects/{project}"],
                        "filter": 'resource.type="gce_instance"',
                        "pageSize": 1,
                    },
                ),
            ),
        }
        results: dict[str, str] = {}
        for operation, (call, arguments) in probes.items():
            try:
                call(*arguments, operation=operation)
                results[operation] = "ok"
            except CloudAccessDenied:
                results[operation] = "denied"
            except OSError as error:
                results[operation] = f"unavailable: {type(error).__name__}"
        return results


@dataclass
class TaskAttempt:
    task_index: int
    attempt_ordinal: int
    outcome: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    assigned_at: datetime | None = None
    exit_code: int | None = None
    instance_id: str | None = None
    zone: str | None = None
    identity_source: str = "unknown"


def _task_index(task: dict) -> int:
    name = task.get("name", "")
    tail = name.rsplit("/", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def parse_task_attempts(task: dict) -> list[TaskAttempt]:
    """Split one task's status events into per-attempt execution records.

    A `RETRIED` event closes the current attempt and names its ordinal, so a
    successful final state never hides an earlier failed attempt.
    """
    index = _task_index(task)
    events = task.get("status", {}).get("statusEvents", []) or []
    attempts: list[TaskAttempt] = []
    current = TaskAttempt(task_index=index, attempt_ordinal=0, outcome="unknown")
    ordinal = 0
    for event in events:
        description = event.get("description") or ""
        occurred = provider_time(event.get("eventTime"))
        reference = INSTANCE_REFERENCE.search(description)
        if reference:
            current.instance_id = reference.group("instance")
            current.zone = reference.group("zone")
            current.identity_source = "task_event_text"
        state = event.get("taskState")
        kind = event.get("type")
        if state == "ASSIGNED":
            current.assigned_at = current.assigned_at or occurred
        elif state == "RUNNING":
            current.started_at = current.started_at or occurred
        if kind == "FAILED":
            current.finished_at = occurred
            current.outcome = "failed"
            current.exit_code = (event.get("taskExecution") or {}).get("exitCode")
        elif kind == "SUCCEEDED":
            current.finished_at = occurred
            current.outcome = "succeeded"
        elif kind == "RETRIED":
            match = ATTEMPT_REFERENCE.search(description)
            current.attempt_ordinal = int(match.group("ordinal")) if match else ordinal
            current.finished_at = current.finished_at or occurred
            if current.outcome == "unknown":
                current.outcome = "failed"
            attempts.append(current)
            ordinal = current.attempt_ordinal + 1
            current = TaskAttempt(
                task_index=index,
                attempt_ordinal=ordinal,
                outcome="unknown",
                instance_id=current.instance_id,
                zone=current.zone,
                identity_source=current.identity_source,
            )
    if current.outcome == "unknown":
        current.outcome = (task.get("status", {}).get("state") or "unknown").lower()
    current.attempt_ordinal = ordinal
    attempts.append(current)
    return attempts


def _instance_from_compute(payload: dict, project: str) -> InstanceObservation:
    scheduling = payload.get("scheduling", {})
    zone = (payload.get("zone") or "").rsplit("/", 1)[-1]
    return InstanceObservation(
        instance_id=str(payload["id"]),
        zone=zone,
        project=project,
        created_at=provider_time(payload.get("creationTimestamp")),
        started_at=provider_time(payload.get("lastStartTimestamp")),
        stopped_at=provider_time(payload.get("lastStopTimestamp")),
        machine_type=(payload.get("machineType") or "").rsplit("/", 1)[-1] or None,
        purchase_model=catalog_purchase_model(scheduling.get("provisioningModel")),
        labels=payload.get("labels", {}) or {},
        source="compute_instance",
    )


def _lifecycle_bounds(entries: Sequence[dict]) -> dict:
    """Recover insert/delete operation boundaries after a VM is deleted."""
    insert_last = delete_first = None
    operations: list[str] = []
    for entry in entries:
        method = (entry.get("protoPayload") or {}).get("methodName") or entry.get("method")
        operation = entry.get("operation") or {}
        timestamp = provider_time(entry.get("timestamp"))
        if operation.get("id") and operation["id"] not in operations:
            operations.append(operation["id"])
        if method and method.endswith("instances.insert") and operation.get("last"):
            insert_last = timestamp
        if method and method.endswith("instances.delete") and operation.get("first"):
            delete_first = timestamp
    return {
        "insert_completed": insert_last,
        "delete_requested": delete_first,
        "operation_ids": operations,
    }


def _machine_shape(job: dict) -> tuple[str | None, str | None]:
    groups = (job.get("status", {}).get("taskGroups") or {}).values()
    for group in groups:
        for instance in group.get("instances", []) or []:
            machine = instance.get("machineType")
            model = catalog_purchase_model(instance.get("provisioningModel"))
            if machine:
                return machine, model
    for policy in job.get("instances_policy") or job.get("allocationPolicy", {}).get(
        "instances", []
    ):
        shape = policy.get("policy", {})
        if shape.get("machineType"):
            return shape["machineType"], catalog_purchase_model(shape.get("provisioningModel"))
    return None, None


def _requested_resources(job: dict) -> tuple[Decimal | None, Decimal | None]:
    groups = job.get("task_groups") or job.get("taskGroups") or []
    for group in groups:
        resource = group.get("computeResource") or group.get("taskSpec", {}).get(
            "computeResource", {}
        )
        if resource:
            cpu = resource.get("cpuMilli")
            memory = resource.get("memoryMib")
            return (
                Decimal(str(cpu)) / 1000 if cpu is not None else None,
                Decimal(str(memory)) if memory is not None else None,
            )
    return None, None


def normalize_batch_job(
    job: dict,
    tasks: Sequence[dict],
    *,
    project: str,
    location: str,
    instances: dict[str, InstanceObservation] | None = None,
    lifecycles: dict[str, dict] | None = None,
    job_source_id: str | None = None,
) -> list[NormalizedAttempt]:
    """Build attempts and the lifetimes they share for one Batch resource."""
    labeled = (job.get("labels") or {}).get(JOB_LABEL)
    source_id = job_source_id or (str(labeled) if labeled else None)
    if not source_id:
        return []
    machine_type, purchase_model = _machine_shape(job)
    vcpu, memory = _requested_resources(job)
    instances = instances or {}
    lifecycles = lifecycles or {}
    attempts: list[NormalizedAttempt] = []
    for task in tasks:
        for parsed in parse_task_attempts(task):
            lifetime = _lifetime_for(
                parsed,
                job=job,
                project=project,
                location=location,
                machine_type=machine_type,
                purchase_model=purchase_model,
                vcpu=vcpu,
                memory=memory,
                instance=instances.get(parsed.instance_id or ""),
                lifecycle=lifecycles.get(parsed.instance_id or ""),
            )
            attempts.append(
                NormalizedAttempt(
                    job_source_id=source_id,
                    source_attempt_id=(
                        f"batch:{job['uid']}:task-{parsed.task_index}:attempt-{parsed.attempt_ordinal}"
                    ),
                    runner=SOURCE_NAME,
                    outcome=parsed.outcome,
                    external_id=job["name"],
                    provider_outcome=job.get("status", {}).get("state"),
                    exit_code=parsed.exit_code,
                    task_index=parsed.task_index,
                    attempt_ordinal=parsed.attempt_ordinal,
                    tool_started_at=parsed.started_at,
                    tool_finished_at=parsed.finished_at,
                    lifetimes=(lifetime,) if lifetime else (),
                    correlation="galaxy_job_label",
                    facts={
                        "batch_uid": job["uid"],
                        "batch_name": job["name"],
                        "assigned_at": parsed.assigned_at.isoformat() if parsed.assigned_at else None,
                        "vm_identity_source": parsed.identity_source,
                    },
                )
            )
    return attempts


def _lifetime_for(
    parsed: TaskAttempt,
    *,
    job: dict,
    project: str,
    location: str,
    machine_type: str | None,
    purchase_model: str | None,
    vcpu: Decimal | None,
    memory: Decimal | None,
    instance: InstanceObservation | None,
    lifecycle: dict | None,
) -> NormalizedLifetime | None:
    if not parsed.instance_id:
        return None
    zone = (instance.zone if instance else None) or parsed.zone
    start = end = None
    method = "batch_task_events"
    facts: dict[str, Any] = {
        "batch_uid": job["uid"],
        "batch_name": job["name"],
        "location": location,
        "vm_identity_source": parsed.identity_source,
        "verified_vm_identity": bool(instance),
    }
    if instance:
        start = instance.started_at or instance.created_at
        end = instance.stopped_at
        method = "compute_instance_timestamps"
        facts["provider_labels"] = instance.labels
        facts["compute_machine_type"] = instance.machine_type
    if lifecycle and (lifecycle.get("insert_completed") or lifecycle.get("delete_requested")):
        start = lifecycle.get("insert_completed") or start
        end = lifecycle.get("delete_requested") or end
        method = "compute_insert_complete_to_delete_request"
        facts["lifecycle_operation_ids"] = lifecycle.get("operation_ids", [])
        facts["lifecycle_uncertainty"] = (
            "Audit operation markers approximate the billable lifetime; they are not an invoice."
        )
    facts["missing_provisioning_overhead"] = start is None
    if start is None:
        start = parsed.assigned_at or parsed.started_at
        end = end or parsed.finished_at
        facts["missing_provisioning_overhead"] = True
    segments = (
        NormalizedSegment(
            source_segment_id="lifetime",
            observed_start=start,
            observed_end=end,
            timing_method=method,
            facts={},
        ),
    )
    return NormalizedLifetime(
        provider="gcp",
        # Project, zone and numeric instance ID identify a GCE VM; retries that
        # reuse the VM resolve to this same key and are charged once.
        resource_key=instance_key(project, zone, parsed.instance_id),
        resource_uid=parsed.instance_id,
        capacity_relationship=CapacityRelationship.dedicated,
        timing_method=method,
        project=project,
        zone=zone,
        region=location,
        machine_type=(instance.machine_type if instance else None) or machine_type,
        purchase_model=(instance.purchase_model if instance else None) or purchase_model or "on_demand",
        observed_start=start,
        observed_end=end,
        requested_vcpu=vcpu,
        requested_memory_mib=memory,
        segments=segments,
        facts=facts,
    )


def _target_key(target: BatchTarget) -> tuple[str, str]:
    return target.job_source_id, target.external_id


def instance_key(project: str, zone: str | None, instance_id: str) -> str:
    return f"gce:{project}/{zone}/{instance_id}"


class CollectionBudgetExpired(TimeoutError):
    """Yield the processed page without advancing past an unfinished target."""


class BatchCollector:
    """Observes a bounded slice of known Batch targets per cycle."""

    source_name = SOURCE_NAME

    def __init__(
        self,
        client: GcpClient,
        targets: Callable[[], Sequence[BatchTarget]],
        *,
        max_targets: int = 25,
        terminal_share: float = 0.2,
        enrich_compute: bool = True,
        enrich_logging: bool = True,
        now: datetime | None = None,
        budget_seconds: float = 60,
        monotonic: Callable[[], float] = time.monotonic,
        completed_lifetimes: Callable[[Sequence[str]], dict[str, tuple[NormalizedLifetime, ...]]] | None = None,
    ) -> None:
        self._client = client
        self._targets = targets
        self._max_targets = max_targets
        self._terminal_share = terminal_share
        self._enrich_compute = enrich_compute
        self._enrich_logging = enrich_logging
        self._now = now
        self._budget_seconds = budget_seconds
        self._monotonic = monotonic
        self._completed_lifetimes = completed_lifetimes

    def _clock(self) -> datetime:
        return self._now or datetime.now(UTC)

    def _page(
        self, items: Sequence[BatchTarget], offset: int, slots: int
    ) -> tuple[list[BatchTarget], int, bool]:
        """One non-overlapping page, with the offset wrapping at the end."""
        if not items or slots <= 0:
            return [], 0, True
        start = offset if offset < len(items) else 0
        window = list(items[start : start + slots])
        next_offset = start + len(window)
        if next_offset >= len(items):
            return window, 0, True
        return window, next_offset, False

    def _select(
        self, targets: Sequence[BatchTarget], state: dict
    ) -> list[BatchTarget]:
        """Plan a page without advancing either durable offset.

        Page active targets fairly while reserving terminal reconciliation.

        Always taking the first N active targets starves the rest whenever the
        active set is larger than one page, and leaves reconciliation no slots
        while work keeps arriving. Both lists page with their own durable
        cursor; when the budget is too small to reserve a reconciliation slot,
        the next cycle gives terminal work the first slots instead, so neither
        list can be starved indefinitely.
        """
        active = [target for target in targets if target.active]
        terminal = [target for target in targets if not target.active]
        reserved = (
            min(len(terminal), max(1, int(self._max_targets * self._terminal_share)))
            if terminal
            else 0
        )
        terminal_first = bool(state.get("terminal_due", False)) and terminal
        if terminal_first:
            terminal_slots = min(len(terminal), self._max_targets)
            active_slots = max(self._max_targets - terminal_slots, 0)
        elif active:
            active_slots = max(self._max_targets - reserved, 1)
            terminal_slots = 0
        else:
            active_slots, terminal_slots = 0, min(len(terminal), self._max_targets)

        active_page, _, _ = self._page(
            active, int(state.get("active_offset", 0)), active_slots
        )
        if not terminal_first:
            terminal_slots = max(self._max_targets - len(active_page), 0)
        terminal_page, _, _ = self._page(
            terminal, int(state.get("terminal_offset", 0)), terminal_slots
        )
        return [*terminal_page, *active_page] if terminal_first else [*active_page, *terminal_page]

    def collect(self, cursor: dict) -> ObservationBatch:
        started = self._clock()
        state = dict(cursor)
        state.setdefault("active_offset", 0)
        state.setdefault("terminal_offset", 0)
        targets = list(self._targets())
        selected = self._select(targets, state)
        state.pop("terminal_due", None)
        terminal_ids = [target.job_source_id for target in selected if not target.active]
        if self._completed_lifetimes and terminal_ids:
            # Loaded for this page only; the full target list grows with history.
            known = self._completed_lifetimes(terminal_ids)
            selected = [
                target if target.active else replace(target, completed_lifetimes=known.get(target.job_source_id, ()))
                for target in selected
            ]
        deadline = self._monotonic() + self._budget_seconds
        self._client.deadline = time.monotonic() + self._budget_seconds
        self._client.request_metrics = {}
        try:
            return self._collect_page(targets, selected, state, started, deadline)
        finally:
            self._client.deadline = None

    def _collect_page(
        self, targets: list[BatchTarget], selected: list[BatchTarget], state: dict,
        started: datetime, deadline: float,
    ) -> ObservationBatch:
        positions = {
            _target_key(target): index
            for group in (True, False)
            for index, target in enumerate(item for item in targets if item.active == group)
        }
        group_sizes = {True: sum(1 for item in targets if item.active)}
        group_sizes[False] = len(targets) - group_sizes[True]
        processed: list[BatchTarget] = []
        active_done = not any(target.active for target in targets)
        budget_exhausted = False
        attempts: list[NormalizedAttempt] = []
        gaps: list[NormalizedGap] = []
        unresolved = 0
        for target in selected:
            if processed and (budget_exhausted or self._monotonic() >= deadline):
                budget_exhausted = True
                break
            try:
                target_attempts, target_gaps = self._collect_target(target, started)
            except CollectionBudgetExpired:
                budget_exhausted = True
                if processed:
                    break
                # A target that cannot finish within the whole budget would
                # otherwise block every later target on every page.
                target_attempts, target_gaps = [], [NormalizedGap(
                    source=SOURCE_NAME, kind="batch_target_budget_exhausted",
                    detail=(f"Batch job {target.external_id} for Galaxy job {target.job_source_id} "
                            "could not be read within the collection time budget; it will be retried."),
                    gap_end=started, recoverable=True,
                )]
            except TimeoutError:
                if not processed:
                    raise
                budget_exhausted = True
                break
            attempts.extend(target_attempts)
            gaps.extend(target_gaps)
            budget_exhausted |= any(gap.kind == "cloud_enrichment_budget_exhausted" for gap in target_gaps)
            unresolved += int(bool(target_gaps and target_gaps[0].kind == "batch_resource_unavailable"))
            processed.append(target)
            offset = positions[_target_key(target)] + 1
            key = "active_offset" if target.active else "terminal_offset"
            state[key] = offset if offset < group_sizes[target.active] else 0
            if target.active:
                active_done = state[key] == 0
        if any(not item.active for item in targets):
            state["terminal_due"] = not any(not item.active for item in processed)
        request_metrics = self._client.request_metrics
        logger.debug("batch_request_summary", extra={"fields": {
            "source": SOURCE_NAME, "requests": request_metrics,
        }})
        return ObservationBatch(
            source=SOURCE_NAME,
            observed_at=started,
            attempts=tuple(attempts),
            gaps=tuple(gaps),
            cursor=state,
            metrics={
                "requests": request_metrics,
                "budget_exhausted": budget_exhausted,
                "targets": len(targets),
                "active_targets": sum(1 for target in targets if target.active),
                "terminal_targets": sum(1 for target in targets if not target.active),
                "observed": len(processed),
                "attempts": len(attempts),
                "unresolved": unresolved,
                "active_offset": state["active_offset"],
                "terminal_offset": state["terminal_offset"],
                "terminal_sweep_wrapped": bool(
                    any(not target.active for target in processed) and state["terminal_offset"] == 0
                ),
            },
            # Another page of active work is drained immediately rather than
            # waiting a full refresh interval.
            exhausted=active_done,
        )

    def _collect_target(
        self, target: BatchTarget, started: datetime
    ) -> tuple[list[NormalizedAttempt], list[NormalizedGap]]:
        job = self._client.get_batch_job(target.project, target.location, target.external_id)
        if job is None:
            return [], [NormalizedGap(
                source=SOURCE_NAME, kind="batch_resource_unavailable",
                detail=(f"Batch job projects/{target.project}/locations/{target.location}/jobs/"
                        f"{target.external_id} was not readable for Galaxy job {target.job_source_id}."),
                gap_end=started, recoverable=True,
            )]
        tasks = self._client.list_batch_tasks(job["name"])
        instances, lifecycles, gaps = self._enrich(job, tasks, target, started)
        attempts = normalize_batch_job(
            job, tasks, project=target.project, location=target.location,
            instances=instances, lifecycles=lifecycles, job_source_id=target.job_source_id,
        )
        completed = {item.resource_key: item for item in target.completed_lifetimes} if not target.active else {}
        return [replace(attempt, lifetimes=tuple(
            completed.get(item.resource_key, replace(
                item, facts={**item.facts, "observed_at": started.isoformat()},
            )) for item in attempt.lifetimes
        )) for attempt in attempts], gaps

    def _enrich(
        self, job: dict, tasks: Sequence[dict], target: BatchTarget, started: datetime
    ) -> tuple[dict[str, InstanceObservation], dict[str, dict], list[NormalizedGap]]:
        instances: dict[str, InstanceObservation] = {}
        lifecycles: dict[str, dict] = {}
        gaps: list[NormalizedGap] = []
        completed = {item.resource_key for item in target.completed_lifetimes} if not target.active else set()
        references = {
            (parsed.instance_id, parsed.zone)
            for task in tasks
            for parsed in parse_task_attempts(task)
            if parsed.instance_id
        }
        created = provider_time(job.get("createTime"))
        # Include provisioning before the job and delayed deletion after it.
        after = (created or started) - timedelta(hours=1)
        terminal = job.get("status", {}).get("state") in {
            "SUCCEEDED", "FAILED", "CANCELLED", "DELETION_IN_PROGRESS",
        }
        end = provider_time(job.get("updateTime")) if terminal else None
        before = (end or started) + timedelta(hours=1)
        logging_throttled = False
        for instance_id, zone in references:
            if instance_key(target.project, zone, instance_id) in completed:
                continue
            try:
                if self._enrich_compute and zone:
                    payload = self._client.get_instance(target.project, zone, instance_id)
                    if payload:
                        instances[instance_id] = _instance_from_compute(payload, target.project)
                if instance_id not in instances and self._enrich_logging and not logging_throttled:
                    try:
                        entries = self._client.instance_lifecycle_entries(
                            target.project, instance_id, after=after, before=before,
                        )
                    except urllib.error.HTTPError as error:
                        if error.code != 429:
                            raise
                        logging_throttled = True
                        gaps.append(NormalizedGap(
                            source=SOURCE_NAME, kind="cloud_enrichment_throttled",
                            detail=(f"Cloud Logging throttled VM lifecycle reads for Galaxy job "
                                    f"{target.job_source_id}; they will be retried."),
                            gap_end=started, recoverable=True,
                        ))
                        continue
                    if entries:
                        lifecycles[instance_id] = _lifecycle_bounds(entries)
            except CollectionBudgetExpired:
                gaps.append(NormalizedGap(
                    source=SOURCE_NAME, kind="cloud_enrichment_budget_exhausted",
                    detail=(f"VM enrichment for Galaxy job {target.job_source_id} reached the collection "
                            "time budget; incomplete lifetimes will be retried."),
                    gap_end=started, recoverable=True,
                ))
                break
            except CloudAccessDenied as denial:
                # Enrichment is optional: degrade with one visible gap rather
                # than repeating a denied call for every VM of the job.
                gaps.append(NormalizedGap(
                    source=SOURCE_NAME, kind="cloud_enrichment_denied",
                    detail=(f"{denial.operation} is denied, so VM lifetimes for Galaxy job "
                            f"{target.job_source_id} are incomplete."),
                    gap_end=started, recoverable=True,
                ))
                break
        return instances, lifecycles, gaps
