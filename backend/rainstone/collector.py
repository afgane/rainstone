"""The unattended collector.

One collector runs per enrolled Galaxy instance, holding a PostgreSQL advisory
lease so a second process cannot double-collect. Each cycle collects one bounded
batch per due source. Network workers feed one accounting writer, which commits
facts, cursors and coalesced cost revisions together. Failures record a visible
status and back off with jitter; they never advance a cursor.

No broker or separate orchestration platform is required, and web availability
is independent of this process.
"""

import functools
import logging
import random
import signal
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from queue import Empty, Queue

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from rainstone import __version__
from rainstone.acquisition import AcquisitionWorker, Delivery
from rainstone.adapters.contracts import (
    NormalizedLifetime,
    NormalizedServerObservation,
    ObservationBatch,
    SourceAdapter,
)
from rainstone.adapters.galaxy_db import GalaxyDatabaseAdapter, discover_capabilities
from rainstone.adapters.galaxy_server import GalaxyServerCollector, HostDescriptor, resolve_host
from rainstone.adapters.gcp_batch import BatchCollector, BatchTarget, HttpGcpClient
from rainstone.adapters.kubernetes import HttpKubernetesClient, KubernetesCollector
from rainstone.baseline import BaselineProfile, classify_job, saved_policy_conflict
from rainstone.catalog import (
    CatalogError,
    active_catalog,
    fetch,
    import_catalog,
    load_file,
    parse_trusted_keys,
)
from rainstone.config import Settings, get_settings
from rainstone.costing import calculate_tenant
from rainstone.db import engine as application_engine
from rainstone.discovery import HostMetadata
from rainstone.doctor import record_report, run_checks
from rainstone.enrollment import read_evidence, source_engine, verify_enrollment
from rainstone.ingestion import (
    apply_batch,
    read_cursor,
    reclassify_baseline,
    record_catalog_refresh,
    record_failure,
    stable_id,
)
from rainstone.logging import Failures
from rainstone.models import (
    CostRevision,
    DeploymentPolicy,
    ExecutionAttempt,
    Job,
    LifetimeAttempt,
    ResourceLifetime,
    Tenant,
)

logger = logging.getLogger("rainstone.collector")

TERMINAL_STATES = {"ok", "error", "deleted", "deleting", "failed", "cancelled"}


class CollectorLeaseUnavailable(RuntimeError):
    """Another collector already holds this instance's lease."""


class BaselinePolicyConflict(RuntimeError):
    """The configured baseline period disagrees with the one saved for its version."""


def _lock_key(key: str) -> int:
    return int.from_bytes(uuid.uuid5(uuid.NAMESPACE_OID, key).bytes[:8], "big", signed=True)


class CollectorLease:
    """A session-scoped PostgreSQL advisory lock held for the process lifetime."""

    def __init__(self, engine: Engine, key: str) -> None:
        self._engine = engine
        self._key = _lock_key(key)
        self._connection = None

    def __enter__(self) -> "CollectorLease":
        self._connection = self._engine.connect()
        acquired = self._connection.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": self._key}
        ).scalar()
        if not acquired:
            self._connection.close()
            self._connection = None
            raise CollectorLeaseUnavailable(
                "another collector holds this instance's lease; only one may collect"
            )
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._connection is not None:
            self._connection.execute(
                text("SELECT pg_advisory_unlock(:key)"), {"key": self._key}
            )
            self._connection.close()
            self._connection = None


@dataclass
class ScheduledSource:
    adapter: SourceAdapter
    interval_seconds: int
    transform: Callable[[ObservationBatch], ObservationBatch] | None = None
    # Reconnects immediately after every batch, like a Kubernetes watch.
    continuous: bool = False
    due_at: float = 0.0
    failures: int = 0
    last_result: dict = field(default_factory=dict)


def baseline_profile(settings: Settings) -> BaselineProfile | None:
    if not (settings.baseline_policy_version and settings.baseline_resource_uid):
        return None
    return BaselineProfile(
        version=settings.baseline_policy_version,
        resource_uid=settings.baseline_resource_uid,
        machine_type=settings.baseline_machine_type,
        region=settings.baseline_region,
        zone=settings.baseline_zone,
        project=settings.gcp_project,
        destinations=settings.baseline_destination_list,
        runners=settings.baseline_runner_list,
        assumptions={"unchanged_vm_size": True, "unchanged_vm_uptime": True},
        effective_from=settings.baseline_effective_from,
        effective_to=settings.baseline_effective_to,
    )


def resolve_baseline_profile(
    session: Session, tenant_id: uuid.UUID, settings: Settings
) -> BaselineProfile | None:
    """The configured profile, bounded by the period its policy version was saved with.

    Collection and reclassification both classify through this, so neither can
    apply a policy outside the period the other respects. A declared period is
    saved with its version the first time it is seen; afterwards the saved
    period governs even if configuration stops declaring one. A declared period
    that disagrees with the saved one classifies nothing, because preferring
    either would silently reprice history. With no period declared or saved,
    the policy covers all time, which the baseline self-check reports.
    """
    profile = baseline_profile(settings)
    if profile is None:
        return None
    saved = session.scalar(
        select(DeploymentPolicy).where(
            DeploymentPolicy.tenant_id == tenant_id, DeploymentPolicy.version == profile.version
        )
    )
    if saved_policy_conflict(saved, settings):
        return None
    if saved is not None:
        return replace(
            profile, effective_from=saved.effective_from, effective_to=saved.effective_to
        )
    if profile.effective_from is not None and session.get(Tenant, tenant_id) is not None:
        session.add(
            DeploymentPolicy(
                id=stable_id(str(tenant_id), "policy", profile.version),
                tenant_id=tenant_id,
                version=profile.version,
                effective_from=profile.effective_from,
                effective_to=profile.effective_to,
                baseline_resource_ids=[profile.resource_uid],
                assumptions={**profile.assumptions, "period": "declared"},
                evidence="Declared by the RAINSTONE_BASELINE_* configuration.",
            )
        )
        session.flush()
    return profile


def extend_baseline_to_host_creation(
    session: Session,
    tenant_id: uuid.UUID,
    settings: Settings,
    servers: Sequence[NormalizedServerObservation],
) -> bool:
    """Start the installation-seeded baseline policy when its host VM was created.

    Enrollment can only date the policy from installation, but the host ran
    Galaxy work before Rainstone arrived, and local work then was on the same
    VM. Every job after the VM's creation ran on it, so the policy moves back to
    the creation time the Compute API reports, never forward, and work already
    collected is reclassified. A period an operator declared is never moved.
    """
    if settings.baseline_effective_from is not None:
        return False
    created = min(
        (server.created_at for server in servers
         if server.resource_uid == settings.baseline_resource_uid and server.created_at),
        default=None,
    )
    policy = session.scalar(
        select(DeploymentPolicy).where(
            DeploymentPolicy.tenant_id == tenant_id,
            DeploymentPolicy.version == settings.baseline_policy_version,
        )
    )
    if (
        created is None or policy is None
        or (policy.assumptions or {}).get("period") == "declared"
        or created >= policy.effective_from
    ):
        return False
    policy.effective_from = created
    policy.assumptions = {**(policy.assumptions or {}), "period": "host_created"}
    session.flush()
    reclassify_baseline(session, tenant_id, resolve_baseline_profile(session, tenant_id, settings))
    return True


def baseline_transform(
    profile: BaselineProfile | None,
) -> Callable[[ObservationBatch], ObservationBatch]:
    def classify(batch: ObservationBatch) -> ObservationBatch:
        return replace(batch, jobs=tuple(classify_job(job, profile) for job in batch.jobs))

    return classify


def batch_targets(
    session: Session, tenant_id: uuid.UUID, settings: Settings
) -> list[BatchTarget]:
    """Batch resources to observe, resolved from Galaxy's recorded external IDs.

    The external ID is combined with the configured project and location; a name
    prefix is never used to infer environment or outcome.
    """
    rows = session.execute(
        select(Job.source_id, Job.state, ExecutionAttempt.external_id)
        .join(ExecutionAttempt, ExecutionAttempt.job_id == Job.id)
        .where(
            Job.tenant_id == tenant_id,
            ExecutionAttempt.external_id.is_not(None),
            ExecutionAttempt.runner.ilike("%batch%"),
        )
        .order_by(Job.source_id)
    ).all()
    targets: dict[tuple[str, str], BatchTarget] = {}
    for source_id, state, external_id in rows:
        name = external_id.rsplit("/", 1)[-1]
        targets[(source_id, name)] = BatchTarget(
            job_source_id=source_id,
            external_id=name,
            project=settings.gcp_project,
            location=settings.gcp_location,
            active=state not in TERMINAL_STATES,
        )
    return list(targets.values())


def completed_batch_lifetimes(
    session: Session, tenant_id: uuid.UUID, source_ids: Sequence[str]
) -> dict[str, tuple[NormalizedLifetime, ...]]:
    """Terminal VM lifetimes whose boundaries both came from provider evidence."""
    complete: dict[str, list[NormalizedLifetime]] = {}
    lifetimes = session.execute(
        select(Job.source_id, ResourceLifetime)
        .join(ExecutionAttempt, ExecutionAttempt.job_id == Job.id)
        .join(LifetimeAttempt, LifetimeAttempt.attempt_id == ExecutionAttempt.id)
        .join(ResourceLifetime, ResourceLifetime.id == LifetimeAttempt.lifetime_id)
        .where(Job.tenant_id == tenant_id, Job.source_id.in_(source_ids),
               ResourceLifetime.tenant_id == tenant_id, Job.state.in_(TERMINAL_STATES), ResourceLifetime.provider == "gcp",
               ResourceLifetime.observed_start.is_not(None), ResourceLifetime.observed_end.is_not(None))
    ).unique().all()
    for source_id, lifetime in lifetimes:
        facts = lifetime.facts or {}
        end_method = facts.get("observed_end_timing_method", lifetime.timing_method)
        provider_methods = {"compute_instance_timestamps", "compute_insert_complete_to_delete_request"}
        # Task completion is not VM deletion. Keep polling fallback boundaries.
        if (lifetime.timing_method not in provider_methods or end_method not in provider_methods
                or facts.get("missing_provisioning_overhead")):
            continue
        complete.setdefault(source_id, []).append(NormalizedLifetime(
            **{name: getattr(lifetime, name) for name in (
                "provider", "resource_key", "resource_uid", "capacity_relationship", "timing_method",
                "project", "zone", "region", "machine_type", "purchase_model", "observed_start",
                "observed_end", "requested_vcpu", "requested_memory_mib",
            )}, facts=dict(facts),
        ))
    return {source_id: tuple(items) for source_id, items in complete.items()}


def tenant_id_for(settings: Settings, session: Session | None = None) -> uuid.UUID:
    """The active fact namespace for this instance.

    The slug names the namespace; its identifier is whatever enrollment
    generated, because replacing a source retires the old namespace under a
    suffixed slug and opens a new one. The derived identifier is only the
    fallback for a namespace that does not exist yet, such as fixture data.
    """
    if session is None:
        with Session(application_engine) as owned:
            return tenant_id_for(settings, owned)
    tenant = session.scalar(select(Tenant).where(Tenant.slug == settings.tenant_slug))
    return tenant.id if tenant is not None else stable_id("tenant", settings.tenant_slug)


class Collector:
    def __init__(
        self,
        settings: Settings,
        sources: Sequence[ScheduledSource],
        *,
        engine: Engine | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._sources = list(sources)
        self._engine = engine or application_engine
        self._clock = clock
        self._sleep = sleeper
        self._tenant_id = tenant_id_for(settings)
        self._catalog_due = 0.0
        self._diagnostics_due = 0.0
        self._failures = Failures(logger, settings.log_repeat_seconds, clock)
        self._progress: dict[str, dict] = {}
        self._summary_at = clock()
        self._coverage_at = float("-inf")
        self._missing_resources: int | None = None
        self._last_catalog: tuple | None = None
        self._last_diagnostics: str | None = None
        self._queue: Queue[Delivery] = Queue(maxsize=settings.collect_queue_size)
        self._workers: dict[str, AcquisitionWorker] = {}
        self._guard_due = 0.0

    @property
    def tenant_id(self) -> uuid.UUID:
        return self._tenant_id

    def _backoff(self, failures: int) -> float:
        ceiling = min(self._settings.collect_max_backoff_seconds, 2 ** min(failures, 10))
        return ceiling / 2 + random.random() * ceiling / 2  # noqa: S311 - jitter only

    @staticmethod
    def _acquire(source: ScheduledSource, cursor: dict) -> ObservationBatch:
        batch = source.adapter.collect(cursor)
        return source.transform(batch) if source.transform is not None else batch

    def collect_source(self, source: ScheduledSource) -> dict:
        """Synchronous bounded collection for explicit one-shot CLI cycles."""
        started = self._clock()
        with Session(self._engine) as session:
            cursor = read_cursor(session, self._tenant_id, source.adapter.source_name)
        try:
            payload = self._acquire(source, cursor)
            delivery = Delivery(source.adapter.source_name, started, self._clock(), payload=payload)
        except Exception as error:  # noqa: BLE001 - persisted by the sole writer
            delivery = Delivery(source.adapter.source_name, started, self._clock(), error=error)
        return self.apply_deliveries([delivery])[0]

    def apply_deliveries(self, deliveries: Sequence[Delivery]) -> list[dict]:
        """Commit a finite queue snapshot with one matching cost calculation."""
        sources = {source.adapter.source_name: source for source in self._sources}
        applying_at = self._clock()
        applied = {}
        revised_sources = set()
        results = []
        changed = False
        with Session(self._engine) as session:
            previous = session.get(CostRevision, self._tenant_id)
            previous_id = previous.id if previous else None
            for delivery in deliveries:
                source = sources.get(delivery.source)
                if delivery.error is not None:
                    record_failure(session, self._tenant_id, delivery.source, repr(delivery.error))
                    results.append({"source": delivery.source, "status": "failed",
                                    "error": type(delivery.error).__name__})
                    continue
                if delivery.source == "diagnostics":
                    record_report(session, self._tenant_id, delivery.payload)
                    results.append({"source": "diagnostics", "status": delivery.payload["overall_status"]})
                    continue
                if delivery.source == "price_catalog":
                    result = self._apply_catalog(session, delivery.payload)
                    changed |= result["status"] in {"refreshed", "bundled"}
                    results.append({**result, "source": "price_catalog"})
                    continue
                batch = delivery.payload
                result = apply_batch(session, self._tenant_id, batch)
                if batch.servers and extend_baseline_to_host_creation(
                    session, self._tenant_id, self._settings, batch.servers
                ):
                    logger.info("baseline_start_corrected")
                changed = True
                applied[id(delivery)] = (source, batch, result)
                results.append(result)
            collected = self._clock()
            revision = calculate_tenant(session, self._tenant_id, reason="collected observations") if changed else previous
            revision_id = str(revision.id) if revision else None
            # All facts and all corresponding source cursors become visible with
            # their matching cost revision, or the entire transaction rolls back.
            session.commit()
        finished = self._clock()
        for delivery in deliveries:
            if delivery.error is not None:
                source = sources.get(delivery.source)
                delay = delivery.retry_seconds
                # Workers schedule their own retries; only coordinator-run
                # sources are rescheduled here.
                if delay is None and source:
                    source.failures += 1
                    delay = self._backoff(source.failures)
                    source.due_at = self._clock() + delay
                retry = {"retry_in_seconds": round(delay, 1)} if delay is not None else {}
                self._failures.failed(delivery.source, delivery.error, source=delivery.source, **retry)
                for result in results:
                    if result["source"] == delivery.source and result.get("status") == "failed":
                        result.update(retry)
            elif delivery.source == "diagnostics":
                status = delivery.payload["overall_status"]
                if status != self._last_diagnostics:
                    logger.log(logging.WARNING if status in {"warn", "fail"} else logging.INFO,
                               "diagnostics_changed", extra={"fields": {"status": status}})
                    self._last_diagnostics = status
                self._failures.recovered("diagnostics")
            elif delivery.source == "price_catalog":
                self._log_catalog(next(result for result in results if result["source"] == "price_catalog"))
            if id(delivery) not in applied:
                continue
            source, batch, result = applied[id(delivery)]
            fields = {"source": batch.source, "cycle_id": uuid.uuid4().hex}
            self._failures.recovered(batch.source, **fields)
            counts = {key: result[key] for key in (
                "jobs", "attempts", "invocations", "gaps", "held_attempts", "pending_applied",
            )}
            counts["changed_calculations"] = int(
                revision_id is not None and str(previous_id) != revision_id and batch.source not in revised_sources
            )
            revised_sources.add(batch.source)
            progress = self._progress.setdefault(batch.source, {"pages": 0})
            progress["pages"] += 1
            for key, value in counts.items():
                progress[key] = progress.get(key, 0) + value
            progress.update({
                **fields, "revision_id": revision_id,
                "collection_ms": round((delivery.completed_at - delivery.started_at) * 1000, 1),
                "queue_delay_ms": round(max(0, applying_at - delivery.completed_at) * 1000, 1),
                "calculation_ms": round((finished - collected) * 1000, 1),
                "adapter_exhausted": batch.exhausted,
            })
            for key in ("targets", "active_targets", "terminal_targets", "observed", "unresolved",
                        "active_offset", "terminal_offset", "terminal_sweep_wrapped", "rows", "reconciled",
                        "budget_exhausted", "mode", "events", "deletions", "nodes", "pods"):
                if key in batch.metrics:
                    progress[key] = batch.metrics[key]
            logger.debug("collection_completed", extra={"fields": {
                **progress, **counts, "requests": batch.metrics.get("requests", {}),
            }})
            gap_types = sorted({gap.kind for gap in batch.gaps})
            if gap_types:
                self._failures.failed(f"{batch.source}.coverage", RuntimeError(),
                                      source=batch.source, gap_types=gap_types)
            else:
                self._failures.recovered(f"{batch.source}.coverage", source=batch.source,
                                        message="Observation resumed; previously recorded gaps remain.")
            source.failures = 0
            source.due_at = self._clock() + (0 if not batch.exhausted else source.interval_seconds)
            result["revision"] = revision_id
            source.last_result = result
        return results

    def _acquire_catalog(self, _cursor: dict) -> tuple:
        try:
            if self._settings.catalog_feed_url:
                return fetch(self._settings.catalog_feed_url,
                             trusted_keys=parse_trusted_keys(self._settings.catalog_trusted_keys)), None
            return None, None
        except (OSError, ValueError) as error:
            return None, str(error)

    def _apply_catalog(self, session: Session, payload: tuple) -> dict:
        artifact, error = payload
        if artifact is not None:
            try:
                with session.begin_nested():
                    result = {**import_catalog(session, artifact), "status": "refreshed"}
            except CatalogError as rejected:
                artifact, error = None, str(rejected)
        if artifact is None:
            current = active_catalog(session)
            if current:
                result = {"catalog_id": current.catalog_id,
                          "status": "last_known_good" if error else "current"}
            elif self._settings.catalog_path:
                artifact = load_file(self._settings.catalog_path,
                                    trusted_keys=parse_trusted_keys(self._settings.catalog_trusted_keys))
                result = {**import_catalog(session, artifact), "status": "bundled"}
            else:
                result = {"status": "unavailable"}
            if error:
                result["error"] = error
        if self._settings.catalog_feed_url:
            record_catalog_refresh(session, self._tenant_id, result)
        return result

    def _log_catalog(self, result: dict) -> None:
        if "error" in result:
            self._failures.failed("price_catalog", RuntimeError(), status=result["status"],
                                  catalog_id=result.get("catalog_id"))
        else:
            self._failures.recovered("price_catalog")
        state = (result["status"], result.get("catalog_id"))
        if state != self._last_catalog:
            logger.info("catalog_changed", extra={"fields": {"status": state[0], "catalog_id": state[1]}})
            self._last_catalog = state

    def _acquire_diagnostics(self, _cursor: dict) -> dict:
        with Session(self._engine) as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            return run_checks(session, self._settings, context="collector")

    def start_workers(self) -> None:
        if self._workers:
            return
        with Session(self._engine) as session:
            for source in self._sources:
                if source.adapter.source_name == "galaxy_db":
                    continue
                name = source.adapter.source_name
                self._workers[name] = AcquisitionWorker(
                    name, functools.partial(self._acquire, source), self._queue,
                    cursor=read_cursor(session, self._tenant_id, name), interval=source.interval_seconds,
                    backoff=self._backoff, clock=self._clock, continuous=source.continuous,
                )
        maintenance = [("price_catalog", self._acquire_catalog, self._settings.catalog_refresh_seconds)]
        if self._settings.diagnostics_enabled:
            maintenance.append(("diagnostics", self._acquire_diagnostics, self._settings.diagnostics_interval_seconds))
        for name, acquire, interval in maintenance:
            self._workers[name] = AcquisitionWorker(
                name, acquire, self._queue, cursor={}, interval=interval,
                backoff=self._backoff, clock=self._clock,
            )
        for worker in self._workers.values():
            worker.start()

    def _drain(self) -> list[Delivery]:
        deliveries = []
        for _ in range(self._queue.maxsize):
            try:
                deliveries.append(self._queue.get_nowait())
            except Empty:
                break
        return deliveries

    def coordinate_once(self) -> list[dict]:
        deliveries = self._drain()
        for source in self._sources:
            if source.adapter.source_name != "galaxy_db" or self._clock() < source.due_at:
                continue
            started = self._clock()
            with Session(self._engine) as session:
                cursor = read_cursor(session, self._tenant_id, "galaxy_db")
            try:
                payload = self._acquire(source, cursor)
                deliveries.append(Delivery("galaxy_db", started, self._clock(), payload=payload))
            except Exception as error:  # noqa: BLE001 - preserve cursor and report failure
                deliveries.append(Delivery("galaxy_db", started, self._clock(), error=error))
        results = self.apply_deliveries(deliveries) if deliveries else []
        stalled = []
        for name, worker in self._workers.items():
            if worker.stalled(self._clock(), self._settings.collect_worker_stall_seconds):
                stalled.append(name)
                self._failures.failed(f"{name}.worker", TimeoutError(), source=name, phase=worker.phase)
            else:
                self._failures.recovered(f"{name}.worker", source=name)
        if not stalled:
            self.heartbeat()
        self.evaluate_guard(force=bool(deliveries))
        self.log_progress()
        return results

    def evaluate_guard(self, *, force: bool = False) -> None:
        if not self._settings.guard_enabled or (not force and self._clock() < self._guard_due):
            return
        self._guard_due = self._clock() + self._settings.collect_interval_seconds
        from rainstone.spend_guard import evaluate_collected

        try:
            with Session(self._engine) as session:
                guard = evaluate_collected(session, self._tenant_id, self._settings)
                session.commit()
                if guard:
                    from rainstone.galaxy_control import GalaxyControl, reconcile_notifications

                    client = GalaxyControl(self._settings)
                    try:
                        reconcile_notifications(session, guard, self._settings, client)
                        session.commit()
                    finally:
                        client.close()
            self._failures.recovered("spend_guard")
        except Exception as error:  # noqa: BLE001 - accounting must continue
            self._failures.failed("spend_guard", error)

    def log_progress(self, *, force: bool = False) -> None:
        now = self._clock()
        active = any(row.get("changed_calculations") for row in self._progress.values())
        interval = self._settings.log_progress_seconds if active else self._settings.log_idle_seconds
        if not force and now - self._summary_at < interval:
            return
        if (any(source.adapter.source_name == "gcp_batch" for source in self._sources)
                and now - self._coverage_at >= self._settings.log_idle_seconds):
            with Session(self._engine) as session:
                resource = (select(ExecutionAttempt.id).join(LifetimeAttempt)
                            .where(ExecutionAttempt.job_id == Job.id).exists())
                self._missing_resources = session.scalar(select(func.count()).select_from(Job).where(
                    Job.tenant_id == self._tenant_id, Job.runner == "gcp_batch",
                    Job.state.in_(TERMINAL_STATES), ~resource,
                ))
            self._coverage_at = now
        logger.info("collection_progress", extra={"fields": {
            "interval_seconds": round(now - self._summary_at, 1),
            "active": active, "sources": self._progress,
            **self.queue_metrics(),
            "finished_batch_jobs_without_resources": self._missing_resources,
            "coverage_age_seconds": round(now - self._coverage_at, 1) if self._missing_resources is not None else None,
        }})
        self._progress = {}
        self._summary_at = now

    def queue_metrics(self) -> dict:
        with self._queue.mutex:
            queued = list(self._queue.queue)
        return {"queue_depth": len(queued), "queue_capacity": self._queue.maxsize,
                "oldest_queued_seconds": round(max(
                    (self._clock() - item.completed_at for item in queued), default=0,
                ), 1)}

    def heartbeat(self) -> None:
        """Record that the loop is alive, independently of dependency health."""
        path = self._settings.collector_heartbeat_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(datetime.now(UTC).isoformat())
            self._failures.recovered("heartbeat")
        except OSError as error:  # noqa: BLE001 - heartbeat is best effort
            self._failures.failed("heartbeat", error)

    def record_capabilities(self) -> dict:
        started = self._clock()
        payload = self._acquire_diagnostics({})
        return self.apply_deliveries([Delivery(
            "diagnostics", started, self._clock(), payload=payload,
        )])[0]

    def refresh_catalog(self) -> dict:
        started = self._clock()
        payload = self._acquire_catalog({})
        return self.apply_deliveries([Delivery(
            "price_catalog", started, self._clock(), payload=payload,
        )])[0]

    def run_once(self) -> list[dict]:
        now = self._clock()
        results = []
        self.heartbeat()
        if self._settings.diagnostics_enabled and now >= self._diagnostics_due:
            results.append(self.record_capabilities())
            self._diagnostics_due = now + self._settings.diagnostics_interval_seconds
        if now >= self._catalog_due:
            results.append({"source": "price_catalog", **self.refresh_catalog()})
            self._catalog_due = now + self._settings.catalog_refresh_seconds
        for source in self._sources:
            if now >= source.due_at:
                results.append(self.collect_source(source))
        self.evaluate_guard()
        self.log_progress()
        return results

    def next_delay(self) -> float:
        now = self._clock()
        due = [source.due_at for source in self._sources] + [
            self._catalog_due,
            self._diagnostics_due,
        ]
        return max(0.0, min(due) - now) if due else 1.0

    def run_forever(self, stop: Callable[[], bool] | None = None) -> None:
        should_stop = stop or (lambda: False)
        self.start_workers()
        try:
            while not should_stop():
                self.coordinate_once()
                self._sleep(0.2)
        finally:
            for worker in self._workers.values():
                worker.stop()
            # Workers never write, so a blocked network call cannot extend the
            # writer lease indefinitely during shutdown.
            for worker in self._workers.values():
                worker.thread.join(timeout=0.2)
        # Only a clean stop applies what is still queued. After a failed
        # snapshot rolls back, later batches from the same sources carry
        # cursors past it, and committing them would skip its observations.
        remaining = self._drain()
        if remaining:
            self.apply_deliveries(remaining)


def build_collector(settings: Settings | None = None) -> Collector:
    """Wire the sources this deployment is configured to observe."""
    settings = settings or get_settings()
    sources: list[ScheduledSource] = []

    if settings.galaxy_source_url is not None:
        galaxy_engine = source_engine(settings)
        capabilities = discover_capabilities(
            galaxy_engine, statement_timeout=settings.galaxy_statement_timeout
        )
        if not capabilities.compatible:
            raise RuntimeError(
                "the Galaxy source schema is not supported: missing "
                + ", ".join(capabilities.missing[:10])
            )
        with Session(application_engine) as session:
            verify_enrollment(
                session, settings, capabilities, read_evidence(settings, capabilities)
            )
            resolve_baseline_profile(session, tenant_id_for(settings, session), settings)
            session.commit()

        def current_profile() -> BaselineProfile | None:
            # Read per batch, because the policy's start can move back once the
            # host VM's creation time is known.
            with Session(application_engine) as session:
                profile = resolve_baseline_profile(session, tenant_id_for(settings, session), settings)
                session.commit()
                return profile

        sources.append(
            ScheduledSource(
                adapter=GalaxyDatabaseAdapter(
                    galaxy_engine,
                    batch_size=settings.galaxy_batch_size,
                    overlap_seconds=settings.galaxy_replay_overlap_seconds,
                    statement_timeout=settings.galaxy_statement_timeout,
                ),
                interval_seconds=settings.collect_interval_seconds,
                transform=lambda batch: baseline_transform(current_profile())(batch),
            )
        )

    if settings.kubernetes_enabled:
        sources.append(
            ScheduledSource(
                adapter=KubernetesCollector(
                    HttpKubernetesClient(
                        namespace=settings.kubernetes_namespace,
                        api_server=settings.kubernetes_api_server,
                    ),
                    # Both identities: the provider's numeric ID, and what
                    # Kubernetes calls the same machine. A node without a
                    # provider ID reports only the latter.
                    baseline_resource_ids=(
                        *(
                            (settings.baseline_resource_uid,)
                            if settings.baseline_resource_uid
                            else ()
                        ),
                        *settings.baseline_node_name_list,
                    ),
                    baseline_descriptor={
                        "machine_type": settings.baseline_machine_type,
                        "region": settings.baseline_region,
                        "zone": settings.baseline_zone,
                        "purchase_model": "on_demand",
                    },
                    watch_seconds=settings.kubernetes_watch_seconds,
                ),
                interval_seconds=1,
                continuous=True,
            )
        )

    if settings.gcp_batch_enabled:
        tenant_id = tenant_id_for(settings)

        def targets() -> list[BatchTarget]:
            with Session(application_engine) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                return batch_targets(session, tenant_id, settings)

        def completed_lifetimes(source_ids: Sequence[str]) -> dict[str, tuple[NormalizedLifetime, ...]]:
            with Session(application_engine) as session:
                session.execute(text("SET TRANSACTION READ ONLY"))
                return completed_batch_lifetimes(session, tenant_id, source_ids)

        sources.append(
            ScheduledSource(
                adapter=BatchCollector(
                    HttpGcpClient(),
                    targets,
                    max_targets=settings.gcp_max_targets_per_cycle,
                    budget_seconds=settings.gcp_collection_budget_seconds,
                    completed_lifetimes=completed_lifetimes,
                    enrich_compute=settings.gcp_enrich_compute,
                    enrich_logging=settings.gcp_enrich_logging,
                ),
                interval_seconds=settings.collect_batch_refresh_seconds,
            )
        )

    if settings.galaxy_server_enabled:
        metadata = HostMetadata()

        def host() -> HostDescriptor:
            # Resolved every cycle, so a descriptor the metadata server could
            # not answer at startup is picked up once it can.
            return resolve_host(
                metadata,
                expected_instance_id=settings.galaxy_server_host_id,
                project=settings.galaxy_server_project,
                zone=settings.galaxy_server_zone,
            )

        sources.append(
            ScheduledSource(
                adapter=GalaxyServerCollector(host, HttpGcpClient()),
                interval_seconds=settings.galaxy_server_refresh_seconds,
            )
        )

    if not sources:
        raise RuntimeError(
            "no collection sources are configured; set the Galaxy source connection "
            "and enable the execution observers this deployment uses"
        )
    return Collector(settings, sources)


def reclassify(settings: Settings | None = None) -> dict:
    """Entry point for `rainstone reclassify-baseline`.

    Holds the collector's lease, so it never writes facts beside a running
    collector, and recalculates once so reports reflect the corrected facts.
    """
    settings = settings or get_settings()
    with CollectorLease(application_engine, settings.collector_lease_key), Session(
        application_engine
    ) as session:
        tenant_id = tenant_id_for(settings, session)
        conflict = saved_policy_conflict(
            session.scalar(select(DeploymentPolicy).where(
                DeploymentPolicy.tenant_id == tenant_id,
                DeploymentPolicy.version == settings.baseline_policy_version,
            )),
            settings,
        )
        if conflict:
            # Without a usable profile every baseline link would be removed.
            raise BaselinePolicyConflict(conflict)
        counts = reclassify_baseline(
            session, tenant_id, resolve_baseline_profile(session, tenant_id, settings)
        )
        revision = calculate_tenant(session, tenant_id, reason="baseline reclassification")
        session.commit()
        return {**counts, "revision_id": str(revision.id)}


def run(settings: Settings | None = None, *, cycles: int | None = None) -> list[dict]:
    """Entry point for `rainstone collect`."""
    settings = settings or get_settings()
    logger.info("collector_starting", extra={"fields": {"version": __version__}})
    collector = build_collector(settings)
    stopping = {"value": False}

    def request_stop(*_: object) -> None:
        stopping["value"] = True
        logger.info("collector_stopping")

    results: list[dict] = []
    with CollectorLease(application_engine, settings.collector_lease_key):
        logger.info("collector_started", extra={"fields": {
            "lease_acquired": True, "version": __version__,
            "sources": [{"source": source.adapter.source_name, "interval_seconds": source.interval_seconds}
                        for source in collector._sources],
        }})
        if cycles is None:
            for received in (signal.SIGINT, signal.SIGTERM):
                signal.signal(received, request_stop)
            collector.run_forever(lambda: stopping["value"])
            collector.log_progress(force=True)
            logger.info("collector_stopped")
            return results
        for _ in range(cycles):
            results.extend(collector.run_once())
        collector.log_progress(force=True)
        logger.info("collector_stopped")
    return results
