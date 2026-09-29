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
range to fill. A bucket is provisional while it holds a running run. Without a
date range, cost with no usable timing is reported as `unplaced` beside the
buckets and is part of the total, so the two reconcile.

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
paused, and `unavailable` once it has finished. An unavailable job's reason says
whether Galaxy recorded when it ran; recalculating alone cannot recover
observations that were never collected.

A price that takes effect after work ran is never applied to it. Such work is
unpriced, and its reason names when the earliest published price takes effect.

The summary distinguishes the requested window from what was observed:
`observation_window` echoes the report bounds, while
`baseline_infrastructure_observed` (and the infrastructure report's
`observed_coverage`) is the span of server observations inside them, or null
when there are none. A tenant restored from a captured snapshot carries an
`imported_snapshot` capability, returned by the summary with its capture time,
source cutoffs and digest; it is real data and is not marked as a demo.

## Galaxy server since its current launch

`/api/infrastructure` and the summary carry `current_launch`, under the same
infrastructure authorization; it is null in the summary for a viewer without
it. It describes the Galaxy host VM's current running session only: machine
type, region, state, `launch_at` and its source, `as_of`, a stale flag and
reason, `hourly_rate` with its catalog provenance, `total_since_launch`,
`known_subtotal`, `completeness` (`complete`, `partial` or `unavailable`), an
unavailable reason, and `calculation_version` with a `calculation_revision`
digest of its inputs. Amounts are decimal strings.

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

Raw job metrics are not part of the revision content digest: they reach reports
only through attempts, lifetimes and job resource hints, which are covered.

Collector health is reported separately from web health: `/api/freshness`
carries per-source status, cursors, lag and recorded observation gaps, and
`/api/status` carries the same read-only self-checks as `rainstone doctor`,
sanitized for download through the normal authenticated route.
