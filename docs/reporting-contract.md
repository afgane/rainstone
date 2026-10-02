# Phase 2A reporting contract

All report endpoints accept the same query fields: cost basis, USD currency,
mode, half-open time interval, IANA timezone, search, full tool identity,
invocation, stable workflow identity, authorized owner, state, runner, destination, capacity relationship,
quality, cost range, calculation revision, pagination, and allowlisted sorting.
The initial page size is 50 and the maximum is 200. A unique internal job ID
breaks sort ties, and missing costs sort after known values in both directions.

The summary request chooses a calculation revision. The browser pins that
revision into every table, chart, detail, and export request and serializes it
in the URL. A revision records the tenant's report-generation marker, which
database triggers advance whenever tenant, owner, job, attempt, resource
lifetime, segment, association, policy, price, workflow membership, or
infrastructure facts change, including through a write that bypasses the
application. Each tenant has exactly one calculation, whose cost lines are
updated in place; a recalculation gives it a new revision ID, and earlier
revisions are not kept. A pinned revision that is no longer current, or whose
marker has moved, returns a conflict instead of mixing figures from two
calculations. The revision also records a content digest, so replaying
identical facts keeps the current revision rather than recalculating. Report
requests use a repeatable-read database snapshot so validation and aggregation
see one state, including while a recalculation is being written.

The default accrued mode clips each observed resource interval to the selected
half-open range. A resource lifetime is split at catalog price boundaries. A
billable minimum is applied once and its uplift is distributed proportionally
over the observed positive-duration lifetime. Local calendar buckets
use the selected timezone through zoneinfo, including daylight-saving
transitions. Open intervals use the fixed revision timestamp and are
provisional. A zero-duration interval is an instant: it belongs whole to the
half-open range that contains it, so known-zero work that lasted no measurable
time keeps its zero in exactly one period.

Work whose cost evidence has no usable timing belongs to no period. A report
without a date range includes it and counts it as temporally unattributed. A
dated report leaves it out of totals, counts, rankings, workflow listings and
CSV export, and describes it separately: `meta.undated` carries its job count,
known subtotal and incomplete count, and the job list returns one page of it as
`undated_items`, paged by `undated_offset` independently of `offset`. Job creation time is never substituted for cost timing.

The completed mode selects successful completions in the interval, uses their
full-job amounts, and places each total on its final successful execution
completion day. Tool mean, median, and p95 exclude unsuccessful, incomplete,
and unknown executions and report their sample and excluded counts. The fixture
calculation uses continuous linear interpolation (R-7) for p95 and labels the
method. Statistics retain an approximation flag when lifecycle evidence is
approximate. Workflow totals
deduplicate job IDs and root totals never add children a second time.

Decimal amounts cross the API and CSV boundary as exact strings. Null means
unknown. Zero is an observed value. A partial amount is a known subtotal and may
also count as incomplete, so coverage categories are explicitly non-disjoint.
A report containing jobs but no known amounts has an unavailable total; a report
with no jobs is an empty result.

Owner and tenant scope is applied before filtering, aggregation, membership
expansion, and export. User and infrastructure reports require administrator
scope in the local multi-user profile. Infrastructure represents a separate
whole-resource scope; job, tool, and owner filters do not apportion it. CSV
exports read database-sortable reports in bounded 500-job batches, stream the
complete authorized filtered result, and neutralize cells that spreadsheet
software could interpret as formulas. Cost-sorted exports retain the in-memory
compatibility path because their ordering depends on calculated report amounts.

## Workflow run reports

`/api/invocations`, `/api/invocations/breakdown` and
`/api/invocations/timeline` share one matching set at one pinned revision. They
accept every shared field and these run-only ones: `workflow_key` (a run's
stored workflow: its family ID, then its workflow ID, then its name),
`run_status`, `focus_from` and `focus_to`, `max_run_amount` with
`boundary_run_id`, `run_sort` (`started_at`, `amount`, `run_total`,
`duration`), and, for the timeline, `bucket`. Run pages default to 20 runs and
are capped at 200.

**Uniform filtering.** Search, the shared filters and the run-only filters are
applied before anything is aggregated, and only matching runs and groups are
returned. Sorting and paging are presentation. Search matches a run's ID, its
workflow ID and its name. A dated report lists the runs that used compute in
the period; a run whose jobs have no usable timing belongs to no period.
`limit` and `offset` apply after filtering and sorting, and `total` counts the
filtered set. `focus_from` and `focus_to` select runs with job timing in that
half-open window, by the reporting mode's own timing rules, and lie inside the
period. Selected runs keep their whole period share; the window is not a new
accounting period. Ties in every sort break on run ID and unknown values sort
last in both directions.

**Grouped selection.** Runs are ordered by their period amount, largest first,
then by run UUID. `max_run_amount` and `boundary_run_id` name an exact suffix
of that order: runs below the amount, plus runs at it whose ID is at or after
the boundary. Comparison is on exact decimals and canonical UUIDs, never on
rounded text, so equal amounts at a cutoff cannot leak into a selection. Runs
with an unknown amount are never part of one. The bounds need `workflow_key`
and describe the grouping that produced them, so the sidebar choices in
`filter_options` are computed without them.

**Totals and coverage.** `/api/invocations` returns `totals` for the whole
filtered set: `amount` is summed over unique job IDs, so a job that belongs to
two runs counts once; `by_status` sums to `run_count`;
`incomplete_run_count` counts runs with unpriced work in the period;
`shared_job_count` counts jobs shared by matching runs; and
`unfiltered_run_count` applies the period and scope but no search or run-only
filter. `filter_options` gives `by_status` counts (every filter except the
outcome) and `workflows` with names and counts (every filter except the
workflow), and keeps a selected option with no matches so it can be cleared.
Every amount is a nullable decimal string: work with no known cost is null, a
mix of known and unknown gives the known subtotal beside an incomplete count,
an empty result is explicitly empty, and only an observed zero is `0`.

**Shared jobs and chart attribution.** A run's `amount` and `run_total` count
every job it contains, including a job another run shares. For charts each
shared job is assigned to the matching root with the lowest canonical UUID,
independent of sorting, paging, caps and chart type, and `chart_amount` is what
a run then contributes; `shared_job_count` counts its jobs another matching run
also holds. Contributions add up to `totals.amount`, so the card, the
breakdown and the timeline agree. This is a display rule, not a claim about
which run caused the work, and filtering can change the assignment. Jobs
reached through several nested memberships under one root are counted once for
that root.

**Run facts.** Each run carries `finished_at`, the latest attempt finish, null
while the run is running, and `duration_seconds`, wall clock from the first
job's submission to that finish or, while running, to the revision time. It is
not billed time.

**Run detail.** `GET /api/invocations/{id}` describes the run as a whole,
whatever period is selected: its `jobs`, `cost_entities` and `cost_breakdown`
are built from the same job records the run's `run_total` sums, nested
workflows included and every job once, so they reconcile with the headline. The
selected period, paging and chart grouping never shape them. Job-level filters
do, exactly as they shape `run_total`. Authorization is the run listing's: a
membership that points at a job the viewer cannot see is counted in
`unavailable_step_count` and otherwise appears nowhere.

Each entry of `jobs` is one distinct job, however many steps it belongs to:

- `amount` is the job's whole cost and null when unknown. `attribution` says
  how it reached the run: `individual` (a positive charge of its own),
  `known_zero`, `unknown` or `unsupported` (negative). A future
  `entity_owned` value is reserved for work whose cost belongs to a shared
  resource.
- `environment` is the verified capacity relationship of its cost lines
  (`dedicated`, `existing`, `elastic_shared`), `multiple` when retries used
  several, and `unknown` when none is established.
- `duration_seconds` is observed tool execution time: the union of its
  execution attempts' intervals, so parallel attempts do not count twice and
  the wait between retries is not counted. It is neither queue time nor the
  time a resource was held. It is null for a job that never started and for a
  finished job with an attempt whose end was never recorded. While a job runs
  it is elapsed time up to the revision, `duration_running` is true and
  `finished_at` is null.
- `order` numbers the jobs from 1 in workflow order: numeric step keys compare
  as numbers, so step 10 follows step 2, and jobs whose keys are not numeric
  follow in submission order. Ties break on the job's source ID.
- `steps` lists every membership, direct or through a child workflow, and
  `cost_entity_id` names the charge the job produced, if any.

`cost_entities` are charges, not jobs: today one `batch_job` per job with a
non-zero known amount, each pointing at its job in `job_ids`. A charge shared
by several jobs would be one `vm_session` entity that lists them all; its jobs
carry no share of it, and a lifetime shared by more than one job is already
unavailable until an allocation policy exists. `cost_breakdown` is `available`
when the positive entities add up exactly to `known_subtotal` (the run total)
and `unavailable`, with a reason, when an amount is negative or non-finite or
the parts do not reconcile. It also counts jobs, entities, known-zero jobs and
unknown jobs; unknown cost is never zero and has no share.

The client draws these as a hundred squares. Parts are made by pooling repeated
jobs of one tool, tool version and environment, then naming parts until they
hold 95% of the known cost, at most eight, none under 1%; a remainder under 2%
is named instead when every piece qualifies, and otherwise pooled as `Other`
with all its members. Squares are apportioned by the largest remainder from
exact amounts, so they total 100 and never feed back into money.

**Breakdown.** Groups are ordered by attributed amount, then name and key. Each
lists at most 200 runs with a known period amount, and the rest fold into
`remainder` with the exact boundary of the first folded run. `whole_run_range`
is computed on the server over every matching run in the group, before that
cap, from whole-run totals: only finished runs with a complete, known total are
included, and the counts of included and excluded runs are returned.

**Timeline.** Buckets follow local clock time in the requested timezone, so a
day has 23 or 25 hourly buckets across a daylight-saving change. `bucket=auto`
chooses hours for a single local day, days up to 92, and Monday-start weeks
beyond. A run that spans buckets appears in each with the cost attributed to
that bucket, the same slicing the daily report uses, so day buckets equal that
report for the same unique jobs. At most 60 pieces are returned per bucket and
the rest fold into `remainder`; empty buckets are omitted and `axis` gives the
range to fill, written like the buckets' own instants. A bucket is provisional
while it holds a running run. Without a date range, cost with no usable timing
is reported as `unplaced` beside the buckets and is part of the total, so the
two reconcile.

## Overview cost over time

`/api/timeline` answers the Overview chart from the shared filters and an
optional `bucket` (`auto`, `hour`, `day` or `week`, resolved as for the
workflow run timeline). Every job in the period is drawn in the column
it accrued in, in one of two pieces: `runs` when a workflow run contains it, and
`individual` when it ran on its own. Runs are not split by workflow, so a column
never has more than two pieces however many workflows there are. A job in
several runs is drawn once; every run that holds it still counts as a run.
Pieces carry `amount`, `job_count`, `run_count` and the failed and still-running
job counts; a column adds its own job and run counts.

`totals` describes the whole period: `amount` (the same figure the summary
reports), `job_count`, `by_outcome` (completed, failed, running, other),
`run_count` and `workflow_count` (the runs and workflows that hold a job in the
period, so they equal the workflow runs totals), and `individual_job_count`.
Column amounts add up to `totals.amount`, and day columns equal the daily report
for the same jobs. A day whose jobs all lack a known cost has a null `amount` in
the daily report and in the timelines alike, with its incomplete count beside
it; only an observed zero is `0`. As elsewhere, an unbounded report keeps cost
with no usable timing in `unplaced` beside the columns, and a dated one leaves
it out.

## Overview details

`/api/overview/details` explains an Overview figure. It takes the shared
filters, normalized as for `/api/timeline` (no workflow runs page filter
applies), plus `scope` and `kind`:

- `scope=interval` with `kind=runs` or `kind=individual` is one chart block.
  `window_from` and `window_to` are required, carry an offset, and are
  intersected with the period; an interval outside it is a 422. Its jobs are
  the block's, with the chart's own accrual chunks, so `amount` and
  `job_count` equal the block's.
- `scope=period` with `kind=runs` (jobs inside workflow runs) or `kind=tools`
  (every matching job) is the whole period.

Any other combination is a 422. As on the chart, a job belongs to the runs
when an authorized root run holds it through an ownership-consistent
membership, nested runs included, and is counted under the lowest-UUID such
root; every other job is individual.

The response carries the effective `scope`, `kind`, `from` and `to`, then
`amount`, `job_count`, `incomplete_job_count`, `provisional` and
`shared_job_count` (scoped jobs held by more than one root), all over the whole
scoped set; `run_count` for runs and `tool_count` for tools; `items`, `total`,
`limit`, `offset` and `meta`. A run item's `amount` is only the cost counted
under it in the scope, beside its `run_total` and `run_status`; a tool item is
a `tool_key` family. Individual jobs are `ScopedJob` rows. Interval items are
ordered by known amount, largest first, then those with no known amount, ties
by ID, and page with `limit` and `offset`.

A period's `ranking` lists at most five items: those with a complete, positive
amount, largest first, ties by ID, over every candidate. `eligible_count`,
`excluded_count` (incomplete, so not comparable) and `zero_count` account for
every run or tool; the excluded ones' known cost stays in `amount`.

## Jobs page

**Tool families.** Each job carries `tool_key`, the identity every version of
its tool shares. For a Tool Shed ID,
`<shed>/repos/<owner>/<repository>/<tool>/<version>`, the terminal version is
removed when the job's recorded `tool_version` agrees with it; every other ID
is its own key. A display name never merges tools. The shared `tool_key` filter
selects one family in every report and in the CSV export, and intersects with
`tool_id` and `tool_version`, which keep their exact meaning. Search matches a
job's source ID, tool ID, the tool ID with underscores read as spaces (the
displayed name), tool version, owner label, and recorded workflow identity.

**Job rows.** `/api/jobs` items add `origin` and the tool's whole execution
time, `duration_seconds` and `duration_running`, under the job details' union
rule. `origin` is `workflow` when an authorized root run holds the job through
an ownership-consistent membership, which is Overview's rule; `unknown` when a
membership exists that cannot be traced to such a run, or a run of the job's
owner created no later than the job has not settled its membership; and
`individual` otherwise. A workflow job also carries `origin_run`, the
earliest of those root runs (by creation, then ID) with its `id` and
`workflow_name`, and `origin_run_count`, how many hold it. All of these are
read in bulk for the returned page only.

**Status pieces.** Amounts are split by the job's recorded status, in the
words Overview counts it (`completed`, `running`, `failed`, `other`), in that
order. Each job is in one piece, and the pieces of a whole add up to it
exactly; each carries `amount`, `job_count` and `incomplete_job_count`.

`/api/jobs/breakdown` groups the matching jobs by `tool_key`. Families with a
positive known amount are ranked by it, then key, and returned up to
`group_limit` (default 12); `remainder` sums the rest. `tool_search` narrows the
listed families by name, key or tool ID and changes no total; `scale` is the
largest family's amount. Families with a known amount of zero go to `server`
when every job is known-zero on the existing Galaxy server, otherwise to
`zero`, and families with no known amount to `unavailable`; those sections
count every family and list those the search matches. `totals` describes the
whole matching set.

`/api/jobs/timeline` takes `bucket` like the other timelines and returns
buckets with status pieces, the same slicing and unplaced handling as the
Overview timeline, and the same `totals`.

`/api/jobs/tool-detail?tool_key=` returns a family under the page's filters
and up to five `contributors`, ranked by their period amount, largest first,
ties by job ID, over every matching job with complete cost; the rest are
`excluded_job_count`. `kind` is `ranked`, `server` (the newest server jobs),
`zero` or `unavailable` (none can be ranked). It also carries the family's
past-job statistics.

`/api/jobs/window-detail?window_from=&window_to=` takes a half-open interval,
clipped to the period. Its jobs are the page's matching jobs, decided over the
whole period, that have cost inside the interval; each carries only that part
of its cost, beside its whole duration. Totals describe every such job and do
not change with `limit` and `offset`. A job can be in several intervals, so
interval job counts need not add up to the period's.

## Resource lifetimes in reports (Phase 2B)

Cost lines are keyed by chargeable resource lifetime and attributed job, not by
attempt. A job detail therefore reports two lists: `resources`, each with its
amount, shape, observed window, timing method and the attempts that shared it;
and `attempts`, each with Galaxy outcome, provider outcome, exit code, task
index and attempt ordinal. An attempt shows an amount only when it is the sole
user of that lifetime; otherwise the row names the attempts sharing the charge
so no report repeats a whole-VM amount. `cost_lines` counts charged lifetimes.

Galaxy and each provider observe the same execution separately, so observations
are reconciled into logical attempts before anything is counted as a repeat.
When provider evidence exists, Galaxy's own record describes one of those
executions unless it carries a resource of its own. Parallel tasks of one
submission are not repeats; a later ordinal of the same task, or a later
submission of it, is. `attempt_count` counts logical attempts,
`repeat_attempt_count` the repeats among them, `observation_count` the raw
observations, and `attempt_evidence` says whether the count rests on provider
observations or on Galaxy's record alone, which cannot show a repeat. In a job
detail each attempt carries a `role` of `first`, `repeat` or `observation`.

The summary reports failed work (`failed_spend`, with
`failed_incomplete_job_count` for failed jobs still missing cost data) and two
different repeat figures: `repeated_job_spend` is the whole cost of jobs that
had a repeat attempt, and `repeat_attempt_spend` only what resources used
solely by repeats cost. A resource shared by a first attempt and its repeat
cannot be divided without a policy, so its amount is reported as
`repeat_attempt_shared_spend` and `repeat_attempt_spend_complete` is false.
A logical attempt with no resource evidence has a cost no line includes: its
job is `partial`, its reason says so, and when it is a repeat inside the report
period the repeat subtotal is incomplete. An attempt without timing counts as
inside every period, so a missing cost never drops out of all of them.

A job with no cost lines reports its evidence state, not an execution state:
`in_progress` while it is queued or running, `not_started` when it is new or
paused, `collecting` for a day after it finished, and `unavailable` after that.
Provider evidence can arrive minutes after Galaxy marks a job finished, and
waits up to a day for its Galaxy job, so a recently finished job is not yet
called unavailable; the day is measured from the calculation time. An
unavailable job's reason says whether Galaxy recorded when it ran;
recalculating alone cannot recover observations that were never collected.

A price that takes effect after work ran is never applied to it. Such work is
unpriced, and its reason names when the earliest published price takes effect.

The summary distinguishes the requested window from what was observed:
`observation_window` echoes the report bounds, while
`baseline_infrastructure_observed` (and the infrastructure report's
`observed_coverage`) is the span of server observations inside them, or null
when there are none. A tenant restored from a captured snapshot carries an
`imported_snapshot` capability, returned by the summary with its capture time,
source cutoffs and digest; it is real data and is not marked as a demo.

Every report's `meta.price_list` names the active price catalog and when its
prices were read from Google Cloud (`observed_at`), or is null when no catalog
is loaded. Its `url` is the published copy of that exact catalog version, so a
reader sees the rates the estimates used rather than Google's page as it reads
today; it is null for a catalog bundled with the release. Estimates always use
Google's published on-demand prices, never an account's own discounted rates.

## Job details

`GET /api/jobs/{id}` describes one whole job. The selected period decides
whether the viewer may open it and how much of it falls inside the period
(`interval_amount`); everything else is built from the job's whole record, so
a whole-job headline never sits beside period-only evidence. `full_job_amount`,
`full_quality`, `full_reason` and `full_capacities` are the whole job's;
`amount`, `quality` and `reason` remain the period's. Clearing report filters
for a detail never widens the tenant or owner scope.

**Timing.** `started_at`, `finished_at` and `duration_seconds` follow the
union-of-executions rule the workflow run's job rows use: concurrent work
counts once, waits between attempts do not count, and a job that never
started, or whose end was never recorded, has no duration. An execution that
finished before it started is unreliable, so it leaves the whole job's
duration null (`timing_issue` is `finished_before_started`); a start before the
submission leaves `before_start_seconds` null (`started_before_submitted`).
A running job's duration is elapsed time to the snapshot, flagged by
`duration_running`, with that time in `duration_cutoff`. `before_start_seconds`
runs from submission (`created_at`) to the first tool start and covers
waiting, provisioning and setup together; it is never called queue time. Each
execution in `attempts` carries its own `duration_seconds` and
`duration_running` under the same rules.

**Resources and executions.** `resources` and `attempts` are the whole job's,
scoped to this job: a resource's `shared_attempt_ids` name this job's
executions only. An execution's `amount` is set only when it alone used every
resource it is credited with, and is the sum of those resources; a null amount
does not mean it shared a charge, which `amount_shared_with_attempts` states.

**Machine size.** A resource's `machine_capacity` gives the machine's own
`vcpu` and `memory_mib`, read from the reviewed registry of priced GCP shapes
(`catalog/gcp-machine-shapes.json`, `source` `published_machine_shape`). Its
`gpu` is the `count` and `model` of the GPUs the machine type always comes
with, such as `{"count": "1", "model": "NVIDIA L4"}` for `g2-standard-4`, and
null for a machine without them. The machine's price already includes them. The
collector records a machine's type, never its capacity. It is null for any
type the registry does not list, and never stands in for `requested_vcpu` or
`requested_memory_mib`, which are what the job asked for.

**Measured use.** `resource_use` reports the allowlisted metrics
(`metrics`, each with a unit) and two comparisons with the request. Galaxy's
cgroup metrics are scalars keyed by job: `cpu.stat.usage_usec` is cumulative
CPU time, and `memory.peak` (cgroup v2) or `memory.max_usage_in_bytes`
(cgroup v1) is a peak in bytes. There is no peak CPU, no sample time and no
attempt identity, so none is reported.

```text
average_cores    = cpu_usec / 1,000,000 / execution_seconds
cpu fraction     = average_cores / requested_vcpu
memory fraction  = peak_bytes / (requested_memory_mib * 1,048,576)
```

`measurement_scope` is `single_execution` only for a finished job with one
logical execution on one resource that is not the Galaxy server;
otherwise it is `unestablished` and `scope_reason` names why
(`galaxy_server`, `running`, `no_execution`, `several_executions` or
`several_resources`). A comparison's `status` is one of:

- `available`: the fraction is set. It is not clamped; use above the request
  exceeds 1.
- `not_recorded`: the metric was never collected. Nothing is shown as zero.
- `invalid_value`: a negative counter.
- `unsupported_scope`: the value cannot be tied to the request. `reason` is
  the scope reason above, `request_scope_unverified` (only a Batch task's
  request is known to describe the tool itself; a Kubernetes pod's admitted
  request can include init containers) or `source_unresolved` (both memory
  peaks were recorded and differ; they are never summed or chosen).
  A Galaxy server's counters describe the host, so their values are withheld.
- `request_unavailable`: no positive request (`request_missing` or
  `request_not_positive`). The measured value is still returned.
- `duration_unavailable`: CPU only; no positive, reliable execution duration.

Quantities are exact decimal strings and ratios keep twelve places; rounding
is left to the client. The metrics are read when the job is opened, not from
the pinned revision, because a metric arriving does not advance the
generation marker.

## Galaxy server since its current launch

`/api/infrastructure` and the summary carry `current_launch`, under the same
infrastructure authorization; it is null in the summary for a viewer without
it. It describes the Galaxy host VM's current running session only: machine
type, region, state, `launch_at` and its source, `as_of`, a stale flag and
reason, `hourly_rate` with its catalog provenance, `total_since_launch`,
`known_subtotal`, `completeness` (`complete`, `partial` or `unavailable`), an
unavailable reason, and `calculation_version` with a `calculation_revision`
digest of its inputs. Amounts are decimal strings. `machine_capacity` holds
the whole VM's published `vcpu`, `memory_mib`, `gpu` and `source`, with the
same shape as job resource capacity. It is null for an unknown machine type
or an unavailable registry; capacities are never guessed from the name.

The total prices `[launch_at, as_of]`, where `as_of` is the last successful
observation, or the provider's stop time once the session has ended. It is
split at catalog price boundaries, and the provider minimum applies once per
session. Time before the earliest applicable price leaves a labeled known
subtotal rather than a backdated price. An unknown launch, a contradicted
shape, a stopped VM without a stop time, or an unpriced shape makes the total
unavailable with its reason; the hourly rate is still given when the shape can
be priced. The result is derived per request from stored facts, so repeated
observations and restarts cannot add to it, and it is marked stale when the
last observation is more than five minutes old or the tenant is an imported
snapshot. Report filters, basis, mode and dates never change it; the timezone
only affects how clients format its timestamps. It is never added to job
totals, and job baseline occupancy is never added to it. The period-based
`items`, `amount` and `observed_coverage` fields remain for compatibility.

`GET /api/infrastructure` also carries `activity` for the current server
session. It is null when its start or cutoff is unknown. Activity ignores
report dates and filters but always applies tenant and owner authorization.
Only executions placed on the existing Galaxy host by local or Kubernetes
runners qualify; Batch executions are excluded. Configured Kubernetes host
node aliases count as server placement when the node has no provider ID. A
verified identity for another VM is excluded. The two runner types share one
presentation and are not exposed as separate activity categories.

Activity carries `from`, `to`, `job_count`, `kind`, `intervals` and `steps`.
Intervals carry `job_id`, `source_id`, `from`, `to` and `running`. They use tool
execution times, clipped to the server session, never queue or pod reservation
time. Missing or invalid timing is omitted. A running execution ends at the
server's observation cutoff; a completed execution with no finish is omitted.
Overlapping attempts of a job merge, but waits between retries stay unfilled.
`job_count` counts distinct jobs with plotted execution evidence.

Steps carry `from`, `to` and the exact concurrent-job `count` on that half-open
interval, with a simultaneous start and finish applied together. Activity is
not a utilization measurement or a claim that unfilled time was idle.
Sessions of up to seven days and at most 500 intervals use `kind=dots` and
include intervals. Longer or denser sessions use `kind=steps`, with intervals
omitted. More than 2,000 step segments use `kind=hidden`, retaining the count
but omitting both plot arrays. The summary does not compute activity.

Raw job metrics are not part of the revision content digest: they reach reports
only through attempts, lifetimes and job resource hints, which are covered.

Collector health is reported separately from web health: `/api/freshness`
carries per-source status, cursors, lag and recorded observation gaps, and
`/api/status` carries the same read-only self-checks as `rainstone doctor`,
sanitized for download through the normal authenticated route.
`/api/freshness` also names the tenant's current `revision_id`, the one a
report requested now would be pinned to, or null while changed facts await
recalculation. It is cheap to read, so an open page polls it to learn that
newer figures exist without asking for the report itself.
