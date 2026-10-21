# Operational logs

The web and collector write one JSON event per line to stderr. Application
timestamps are UTC, formatted as `2026-10-20 13:14:47,855`. Every event includes
`timestamp`, `level`, `component` and `event`. Kubernetes captures the stream;
Rainstone does not maintain log files inside its application containers.

## Collector

Startup records the version, acquired lease, enabled sources and intervals.
Shutdown records the stop request and the final progress summary. A lease
conflict is a warning; an unexpected fatal failure has a stack trace and the
process exits unsuccessfully.

`collection_progress` summarizes completed pages since the previous summary.
The default interval is 60 seconds when calculations changed, or 300 seconds
otherwise. Summaries run on the coordinator; slow network acquisition does
not delay them. Database collection and accounting work can delay a summary.
Counts of jobs, attempts and invocations are observations,
not distinct jobs or a claim that every observed record changed.
`changed_calculations` counts revised calculations. Collection and calculation
durations, cycle and revision IDs describe the latest page for each source.
`collection_ms` measures acquisition; `queue_delay_ms` measures the wait
before applying a queued batch. `calculation_ms` is shared by batches in the
same accounting transaction and must not be summed across those batches.
`changed_calculations` counts each shared revision once per participating
source. Queue depth, capacity and oldest queued batch age accompany summaries.

Batch target counts, page sizes and offsets are latest-page gauges. A terminal
sweep wrapping means its paging reached the end of the current target list;
it does not guarantee complete resource evidence. Active and terminal lists
change while jobs arrive and finish. `adapter_exhausted` describes adapter
scheduling, not complete historical coverage.

`finished_batch_jobs_without_resources` separately counts finished Batch jobs
without any recorded resource link, within the collector's tenant. It is
refreshed at most once per idle interval; `coverage_age_seconds` reports its
age. Missing prices, incomplete lifetimes and jobs still running are outside
this count. Null means the count has not been obtained or Batch is disabled.

Source failures and coverage problems log immediately on transition, then at
most once per repeat interval for the same failure. Recovery logs once.
Failure events carry the error class and, where available, operation, HTTP
status, SQLSTATE or system error name. Catalog and diagnostic state changes
also produce events. Coverage recovery explicitly says observation resumed
and earlier gaps remain. Worker stalls log separately from source failures.
DEBUG adds page completions and provider request durations without dumping
cursors, request URLs or provider payloads. Batch completion fields include
per-operation request counts and total milliseconds for `batch.jobs.get`,
`batch.tasks.list`, `compute.instances.get`, and `logging.logEntries.list`.
These include failed requests and credential acquisition time. A separate
`batch_request_summary` also records totals for completed Batch pages.

## Web

Report requests log method, route template, status, elapsed milliseconds and a
generated request ID. Responses include `X-Request-ID`, including unexpected
500 responses. Successful static-file requests and health, readiness and
freshness polling stay quiet. Probe failures and recovery log as transitions.
Slow report requests and other unsuccessful requests are warnings; server
errors are errors. The default slow-request threshold is two seconds.

An unexpected exception is logged once with its stack frames. Exception
messages, source lines, query strings, headers, request bodies, user IDs and
literal path parameters are omitted: those can contain credentials, SQL
values or other private data. A stack frame records file, line and function.
Uvicorn's duplicate access and already-reported exception logs are suppressed.

## Configuration

The chart exposes these controls under `logging`; environment variables also
work for deployments outside Helm. Intervals and thresholds must be positive.

| Helm value | Environment variable | Default |
| --- | --- | --- |
| `level` | `RAINSTONE_LOG_LEVEL` | `INFO` |
| `progressSeconds` | `RAINSTONE_LOG_PROGRESS_SECONDS` | `60` |
| `idleSeconds` | `RAINSTONE_LOG_IDLE_SECONDS` | `300` |
| `repeatSeconds` | `RAINSTONE_LOG_REPEAT_SECONDS` | `300` |
| `slowRequestSeconds` | `RAINSTONE_LOG_SLOW_REQUEST_SECONDS` | `2` |

Levels are `DEBUG`, `INFO`, `WARNING` and `ERROR`. Use DEBUG temporarily for
diagnosis. CLI command results on stdout retain their machine-readable format.

## PostgreSQL

The bundled database uses native stderr logs with UTC timestamps, process IDs
and application names. PostgreSQL's native timestamp uses a decimal point
before milliseconds and a timezone suffix; the application formatter does not
process database output.

Startup, shutdown, recovery, database errors, deadlocks and prolonged lock
waits remain visible. Successful connections, disconnections, checkpoints and
routine statements are quiet. Error statement logging is disabled except at
PANIC severity, parameter logging is disabled, and terse error verbosity omits
detail and context. Database errors themselves may still contain values.

Slow SQL statement logging is disabled by default. Enable detailed SQL logging
only temporarily while troubleshooting, taking care with query values.
External database operators manage their own logging configuration. Settings
and their tradeoffs are described in the
[PostgreSQL logging documentation][postgres].

[postgres]: https://www.postgresql.org/docs/17/runtime-config-logging.html
