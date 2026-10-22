# Collection and resource accounting

`rainstone collect` runs independently of `serve`, from the same image, with one
active collector per enrolled Galaxy instance. It holds a PostgreSQL advisory
lease, so a second process refuses to collect rather than double-counting. Web
availability does not depend on it.

One writer per instance also keeps writes contention-free: advancing the
report-generation marker takes a per-tenant row lock, so two concurrent
ingestions of the same tenant would serialize.

Network acquisition runs independently: Kubernetes continuously reconnects its
list/watch, while Batch, host observation, diagnostics and catalog downloads
have separate workers. Workers perform no database writes. The Galaxy database
source remains on the coordinator with its read-only statement timeout.

Workers feed a bounded in-memory queue. The coordinator drains a finite queue
snapshot, applies its batches, recalculates costs once, and commits the facts,
source cursors and matching revision together. Explicit `collect --cycles N`
uses bounded synchronous cycles for one-shot collection. A failure records a
visible source status, backs off with jitter, and leaves its cursor alone.

A worker can consume ahead of the committed cursor in memory. Restart recovery
uses the durable cursor and replays observations safely. Queue size defaults to
64 completed batches, plus at most one pending batch per worker. Queue depth,
oldest batch age and collection-to-application delay are logged. There is no
durable inbox: a process stopped with queued observations can still encounter
expired watch history on restart, which records an unrecoverable gap. A clean
stop applies the queue before exiting. A failed transaction exits without
applying later queued batches, whose cursors would skip the rolled-back ones.

The coordinator writes the heartbeat while making progress. A worker whose
acquisition exceeds its progress deadline also stops heartbeat updates; normal
source errors, retry waits and waiting on a full queue do not. A full queue
means the writer is slow, and a stuck writer stops the heartbeat itself.
The worker deadline defaults to 180 seconds and is separate from the chart's
300-second heartbeat age limit. An unresponsive worker is eventually restarted
with the process, while ordinary dependency failures leave other workers alive.

An unchanged set of source facts keeps the existing revision. A changed one
updates cost lines in place, writing only lines whose values changed, so
storage follows work rather than the number of recalculations.

## Galaxy database extraction

The adapter discovers schema capabilities first and refuses to run against an
unsupported schema. Every statement names its columns, runs read-only with a
statement timeout, and reads logical job facts only: no command lines,
stdout/stderr, tracebacks, credentials, dataset contents or the pickled
`destination_params` blob. Resource hints come from allowlisted numeric metrics.

Collection has three phases:

| Phase | Behavior |
| --- | --- |
| Backfill | Pages by stable job ID up to a recorded upper bound |
| Incremental | Pages by `(update_time, id)` with a replay overlap |
| Reconciliation | Nonterminal jobs, recently terminal jobs, active invocation trees, and a wrapping sweep of older jobs in bounded batches |

Reconciliation exists because job update timestamps are not a complete change
feed: a metric or a collection membership can appear without the parent job's
timestamp changing. The sweep wraps when it reaches the end, so older records
are eventually revisited.

A finished job that Galaxy never dispatched is not collected: one with no
runner and no recorded start or finish time. Nothing can ever place or time
such a job, so it could only be reported as undated work. This covers jobs
carried over in Galaxy's database from before Rainstone was installed, and
tools Galaxy completes without a job runner. A job collected while still queued
and later finished without being dispatched, such as one deleted from the queue,
is withdrawn with its attempts and workflow memberships. A job that did run
after installation stays collected even if its execution evidence never
arrives, so a collection failure remains visible as undated work.

Workflow attribution uses the recursive query proven on the AnVIL dev instance:
root invocations expand through subworkflow associations, and each step
contributes direct jobs plus implicit-collection expansions. Invocation
ownership comes from the invocation's history, because this schema has no
`workflow_invocation.user_id`. The value stored as an invocation's
`workflow_version` is Galaxy's internal workflow ID, not the version number
Galaxy's own screens show, so reports carry it but never display it. Job ownership is enforced separately, so a
mismatched membership never widens a viewer's authorized cohort. Invocations
record whether their step scheduling has settled; membership is revisited until
it has.

## Kubernetes observation

Pods are observed by list plus watch, tracking the list resource version,
relisting after an expired version, and recording an **unrecoverable** gap for
that window, because pods deleted while disconnected cannot be recovered.

A pod's occupancy of node capacity is one lifetime, keyed by pod UID, and the
node keeps its own identity in `resource_uid`. Reserved time starts when the pod
is scheduled, so image pulls and setup consume capacity while unscheduled queue
time does not. Tool time is recorded separately, each container run is its own
segment, and restarts do not merge into one interval. Admitted requests include
init containers. A node without a provider ID gives no verified VM identity, and
that qualification travels with the observation.

A watch delivers each pod event once, and a short tool run outside a workflow
can start, finish and be deleted before the Galaxy collector has seen its job.
Provider evidence for a job that has not been collected yet is held in
`pending_attempt`, keeping only its latest observation, and applied when the
job arrives. Evidence still waiting after a day is dropped and recorded as an
unrecoverable `provider_evidence_without_galaxy_job` gap.

Only watch Status code 410 with reason `Expired` or `Gone` is treated as
expired history; other stream errors fail and retry the source. Gap starts
use the previous watch's completion time. Recovery means observation
resumed; it never erases a historical gap.

## GCP Batch, Compute and Logging observation

Galaxy stores a short Batch job name, so every read combines it with the
configured project and location and retains the full resolved name and UID. A
name prefix never implies an environment or an outcome; correlation uses the
provider's Galaxy job label.

Provider retries appear in **task** status events, not in the top-level job
status. The collector splits task events into per-attempt records with task
index, attempt ordinal, exit code and provider outcome, so a successful final
state never hides an earlier failed attempt. Galaxy state and exit code stay
separate from provider state: a `SUCCEEDED` Batch task never overwrites a Galaxy
error.

VM identity parsed from task-event text is labeled as a text-parsed correlation
hint. Live Compute instance timestamps are preferred; Logging insert and delete
operation markers recover a lifecycle window after a VM is deleted, with their
operation IDs and an explicit uncertainty note. When only task events are
available, the lifetime is marked as missing provisioning overhead. Every API
listing is paginated.

## Resource lifetimes and attempts

A **resource lifetime** is one chargeable provider resource, keyed by project,
zone and numeric instance ID for a GCE VM. Attempts associate with it. CI job
336 proves two attempts can use one VM, so:

- the lifetime is priced once per basis and component;
- the provider minimum applies once to the lifetime, with its uplift
  distributed proportionally across observed positive-duration windows, never
  once per attempt or per daily bucket;
- the charge is shown as shared across those attempts, and no attempt row
  repeats the full amount;
- two different VMs used by retries still produce two lifetime charges.

If more than one Galaxy job shares a dedicated lifetime, the charge becomes
unavailable with a reason, pending an explicit allocation policy and occupancy
coverage.

The Galaxy host is not such a case. Verified baseline capacity keeps its
known-zero additional spend however many jobs share it, and its cost is never
divided among them: it is reported once, as the Galaxy server's cost. No
allocation policy for the host is planned.

Several observations of one resource are merged by evidence precedence:
provider-billable, then live Compute timestamps, then audit lifecycle markers,
then Kubernetes occupancy, then task events, then configured baseline
occupancy. Lower-precedence evidence never overwrites better evidence.

## Galaxy server session

The `galaxy_server` source observes the Galaxy host VM itself, independently of
job collection and Batch. It resolves the host on startup and every 60 seconds
(`RAINSTONE_GALAXY_SERVER_REFRESH_SECONDS`), backing off on failure like every
other source.

The host is the configured instance (`RAINSTONE_GALAXY_SERVER_INSTANCE_ID`,
defaulting to the baseline resource UID). Local instance metadata supplies its
project, zone, name, shape and scheduling model only when its instance ID
matches, so a collector never prices whatever machine it happens to run on. A
collector that does not run on the host also names the host's project and zone,
and then metadata is not read.

One Compute `instances.get`, using the deployment's existing metadata-issued
credential, supplies the status, shape, provisioning model and
`lastStartTimestamp`. That timestamp is the start of the current running
session; `creationTimestamp` describes the VM's first creation and is never
substituted. A denied or empty read, or a response describing a different
numeric ID, yields an observation without a launch time and a reason. No new
IAM binding, Cloud Logging query or billing export is used.

Rainstone keeps one session row per tenant, keyed by VM identity and launch
time. A repeated observation of the same key only moves its last observation;
a different key replaces the row, so a later start or a different VM begins a
fresh total and no earlier session is kept. Once a launch time is known, a
later observation that cannot establish one leaves the session frozen at its
last successful observation and marks the source degraded. Shape evidence that
contradicts the shape a session was identified with is kept on the row until a
new session replaces it. Heartbeat-only updates do not advance the report
generation, and repeated identical observations share one ingestion event.

## Batch refresh fairness

Active Batch resources page through a durable cursor rather than always taking
the first slice, because a sustained active set larger than one page would
otherwise starve the rest and leave short-lived VM observations unrecorded.
Terminal reconciliation keeps reserved capacity; when the configured budget is
too small to reserve any, the next cycle leads with reconciliation so neither
list starves. A cycle that has not covered the active list reports itself
unexhausted and is drained immediately instead of waiting a full interval.

Batch acquisition has a 60-second default time budget and individual request
deadlines. Only processed targets advance their active or terminal offsets.
If time runs out before terminal work gets a slot, the next page leads with
terminal work, so neither group is permanently starved. A timeout during VM
enrichment retains acquired evidence with a recoverable gap and retries the
incomplete lifetime on a later sweep. A target that cannot be read within the
whole budget records a recoverable `batch_target_budget_exhausted` gap and is
retried on a later pass, so it cannot block every target after it.

Logging lifecycle reads explicitly bound timestamps from job creation with a
one-hour provisioning margin through job completion with a one-hour deletion
margin. Active jobs use the current poll as the upper
bound. Terminal VM lifetimes with provider evidence for both
boundaries reuse their saved observations instead of repeating Compute and
Logging reads. Task-event fallback boundaries do not qualify as complete;
late provider evidence continues to be collected. Complete lifetimes are
loaded only for the terminal targets on the current page. A Logging HTTP 429
stops Logging reads for that job, and a denied enrichment call stops its
enrichment, each with one recoverable gap naming the Galaxy job instead of
failing the entire Batch page.

The chart exposes `collector.gcpBatch.collectionBudgetSeconds`,
`collector.queueSize`, and `collector.workerStallSeconds`. Corresponding
settings are `RAINSTONE_GCP_COLLECTION_BUDGET_SECONDS`,
`RAINSTONE_COLLECT_QUEUE_SIZE`, and `RAINSTONE_COLLECT_WORKER_STALL_SECONDS`.
Increase the worker deadline when deliberately increasing an acquisition
budget beyond it; a larger deadline does not fix a slow or saturated writer.

## Price coverage

A catalog declares its coverage — the published one claims the US regions it
prices, the `t2d`, `n2` and `g2` families, on-demand — so a region it never
claimed and a claimed region it could not price are distinguishable rather than
one number. Work outside a catalog's coverage stays visibly **unpriced** rather
than borrowing another region's or a different shape's rate. The integration
tests import a hand-captured pilot catalog (`fixtures/price-catalog-pilot.json`)
that claims only `us-central1`, so the CI corpus's nine N2 shapes in `us-east4`
exercise exactly that. Regional variation is ordinary price data for the
publisher to maintain, not an override an operator keeps. `rainstone catalog
coverage` lists what is claimed and what can be priced, and `/api/catalog`
reports the same through the UI.

Catalog artifacts are content-addressed and immutable: a published catalog ID
cannot be replaced with different content. A refresh validates the artifact
before trusting it, imports prices and activates the version in one transaction,
and on failure keeps the last known good catalog. Each refresh from the feed is
recorded as the `price_feed` source: a failure is logged, marks that source
degraded, and turns the `price_catalog` self-check into a warning that names
the error, so a feed that stops answering does not pass for an aging catalog.
Without a configured feed the active catalog is a pinned historical snapshot,
and the status report says so.

An artifact from a feed always needs a verified Ed25519 signature over its
canonical content, against a release-pinned public key configured as
`key_id:base64-public-key` pairs. That is not a setting: an attacker who can
answer the feed can also remove a signature block, so optional enforcement would
be no enforcement. The bundled artifact ships inside the release image and is
trusted by provenance instead. Trusting two keys at once is how a key is
rotated: publish with the new key while the old one is still trusted, then drop
the old key. A digest the artifact declares about itself is an integrity aid
only — an attacker controls both the content and that digest — so it never
establishes authenticity. A feed cannot be configured without trusted keys, and
a verification failure leaves the working catalog in place.
