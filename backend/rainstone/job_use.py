"""What one job measured, compared with what it requested.

Galaxy's cgroup metrics are scalars keyed by job: there is no sample time, no
peak CPU and no attempt identity. A ratio is therefore produced only where a
single, finished execution on a single resource makes the job's counters and
its request describe the same workload. Everywhere else the raw value is kept
and the comparison says why it was not made; nothing missing becomes zero.
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

MICROSECONDS = Decimal(1_000_000)
BYTES_PER_MIB = Decimal(1_048_576)
RATIO_PLACES = Decimal("0.000000000001")

CPU_TIME = ("cgroup", "cpu.stat.usage_usec")
# cgroup v2 and v1 name the same peak differently. Neither is `memory.max`,
# which is a configured limit and is not collected.
MEMORY_PEAKS = (("cgroup", "memory.peak"), ("cgroup", "memory.max_usage_in_bytes"))

METRIC_UNITS = {
    ("core", "galaxy_slots"): "slots",
    ("core", "galaxy_memory_mb"): "MB",
    ("core", "runtime_seconds"): "seconds",
    ("core", "start_epoch"): "seconds since epoch",
    ("core", "end_epoch"): "seconds since epoch",
    CPU_TIME: "microseconds",
    MEMORY_PEAKS[0]: "bytes",
    MEMORY_PEAKS[1]: "bytes",
}

# A Batch task's request is the task's own compute resource, which is what its
# cgroup measures. A Kubernetes pod's admitted request can include init
# containers that the tool's cgroup never sees, so it is not compared.
TASK_REQUEST_TIMING_METHODS = {
    "batch_task_events",
    "compute_instance_timestamps",
    "compute_insert_complete_to_delete_request",
}

Metrics = dict[tuple[str, str], Decimal]


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(RATIO_PLACES)


def _scope_problem(
    running: bool, executions: Sequence[tuple[datetime | None, datetime | None]], resources: Sequence[dict]
) -> str | None:
    """Why the job's counters cannot be tied to one execution on one resource."""
    if any(resource["capacity_relationship"] == "existing" for resource in resources):
        # A Galaxy server's counters describe the host, not this job.
        return "galaxy_server"
    if not executions:
        return "no_execution"
    if running:
        return "running"
    if len(executions) > 1:
        return "several_executions"
    if len(resources) > 1:
        return "several_resources"
    return None


def _duration_seconds(execution: tuple[datetime | None, datetime | None]) -> Decimal | None:
    started, finished = execution
    if started is None or finished is None or finished <= started:
        return None
    return Decimal(str((finished - started).total_seconds()))


def _request(resources: Sequence[dict], key: str) -> tuple[Decimal | None, str | None]:
    """The single resource's positive request, or why there is none to compare with."""
    if len(resources) != 1 or resources[0][key] is None:
        return None, "request_missing"
    value = Decimal(resources[0][key])
    return (value, None) if value > 0 else (None, "request_not_positive")


def _request_scope_verified(resources: Sequence[dict]) -> bool:
    return len(resources) == 1 and resources[0]["timing_method"] in TASK_REQUEST_TIMING_METHODS


def _cpu(
    metrics: Metrics, problem: str | None, executions: Sequence[tuple[datetime | None, datetime | None]],
    resources: Sequence[dict],
) -> dict:
    section = {
        "status": "not_recorded", "reason": None, "cpu_seconds": None, "duration_seconds": None,
        "average_cores": None, "requested_vcpu": None, "request_fraction": None,
    }
    requested, request_problem = _request(resources, "requested_vcpu")
    section["requested_vcpu"] = _text(requested)
    raw = metrics.get(CPU_TIME)
    if raw is None:
        return section
    if raw < 0:
        return {**section, "status": "invalid_value"}
    if problem == "galaxy_server":
        return {**section, "status": "unsupported_scope", "reason": problem}
    cpu_seconds = raw / MICROSECONDS
    section["cpu_seconds"] = _text(cpu_seconds)
    if problem:
        return {**section, "status": "unsupported_scope", "reason": problem}
    duration = _duration_seconds(executions[0])
    if duration is None:
        return {**section, "status": "duration_unavailable"}
    average = cpu_seconds / duration
    section["duration_seconds"] = _text(duration)
    section["average_cores"] = _text(average.quantize(RATIO_PLACES))
    if request_problem:
        return {**section, "status": "request_unavailable", "reason": request_problem}
    if not _request_scope_verified(resources):
        return {**section, "status": "unsupported_scope", "reason": "request_scope_unverified"}
    return {**section, "status": "available", "request_fraction": _text(_ratio(average, requested))}


def _memory(metrics: Metrics, problem: str | None, resources: Sequence[dict]) -> dict:
    section = {
        "status": "not_recorded", "reason": None, "peak_bytes": None, "source": None,
        "requested_memory_mib": None, "request_fraction": None,
    }
    requested_mib, request_problem = _request(resources, "requested_memory_mib")
    section["requested_memory_mib"] = _text(requested_mib)
    recorded = {name: metrics[(plugin, name)] for plugin, name in MEMORY_PEAKS if (plugin, name) in metrics}
    if not recorded:
        return section
    if len(set(recorded.values())) > 1:
        # Nothing says which cgroup version is authoritative, and they are
        # never summed or chosen for the percentage they give.
        return {**section, "status": "unsupported_scope", "reason": "source_unresolved"}
    source, peak = next(iter(recorded.items()))
    if peak < 0:
        return {**section, "status": "invalid_value"}
    if problem == "galaxy_server":
        return {**section, "status": "unsupported_scope", "reason": problem}
    section.update(peak_bytes=_text(peak), source=source)
    if problem:
        return {**section, "status": "unsupported_scope", "reason": problem}
    if request_problem:
        return {**section, "status": "request_unavailable", "reason": request_problem}
    if not _request_scope_verified(resources):
        return {**section, "status": "unsupported_scope", "reason": "request_scope_unverified"}
    return {
        **section, "status": "available",
        "request_fraction": _text(_ratio(peak, requested_mib * BYTES_PER_MIB)),
    }


def job_resource_use(
    metrics: Metrics,
    *,
    running: bool,
    executions: Sequence[tuple[datetime | None, datetime | None]],
    resources: Sequence[dict],
) -> dict:
    """The job's measured use, with a comparison only where its evidence allows one.

    `executions` are the logical executions' recorded start and finish;
    `resources` are the job's resource entries, as a job detail reports them.
    """
    problem = _scope_problem(running, executions, resources)
    return {
        "measurement_scope": "unestablished" if problem else "single_execution",
        "scope_reason": problem,
        "cpu": _cpu(metrics, problem, executions, resources),
        "memory": _memory(metrics, problem, resources),
        "metrics": [
            {"plugin": plugin, "name": name, "value": _text(value), "unit": METRIC_UNITS.get((plugin, name))}
            for (plugin, name), value in sorted(metrics.items())
        ],
    }
