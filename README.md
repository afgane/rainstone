# Rainstone v2

Rainstone reports estimated compute cost for work performed by Galaxy.
The dashboard shows what analyses cost, with coverage and missing data
explicit. It includes job, tool and workflow reports, the Galaxy server's
separate cost, and links that preserve the selected report view.

On single-user AnVIL deployments with GCP Batch enabled, Rainstone also
provides a Batch spend limit. No limit is active until the user sets one.
The limit includes recorded Batch costs already accrued and excludes the
Galaxy server. When estimated spending approaches it, new Batch dispatch
pauses; the user can also choose to stop outstanding Batch jobs. This is
best effort, and final spending may exceed the limit. The Galaxy server
keeps running. See [Batch spend limits](docs/spend-limit.md).

The web application and collector keep reporting state in Rainstone's own
database. Collection reads Galaxy's database without changing it. When a
spend limit is enabled, the collector uses the Galaxy API for notifications
and optional cancellation. The web process holds no Galaxy control key.
See [collection](docs/collection.md) and [deployment](docs/deployment.md).

The bundled demonstration starts with sanitized 2026-09-19 Phase 0
observations. It includes the three recorded dedicated Batch calculations, a
cross-runner retry, a mixed Kubernetes/Batch invocation, a nested collection
invocation, known-zero existing capacity, unknown execution topology, two
owners, and a separate baseline-VM interval. Clearly marked synthetic cases add
a DST boundary, in-progress and awaiting-calculation work, output reuse, and a
same-VM provider retry whose one lifetime is charged once across two attempts.
No operational endpoint, credential, raw log, or user dataset is included.

## Run locally

Docker with Compose is the only required host dependency.

```console
make dev
```

Open <http://localhost:5173>. The first run builds the toolchains, waits for
PostgreSQL, applies the Alembic migration, and idempotently ingests the fixture.
`make dev-down` retains data; `make dev-reset` explicitly removes only the
Compose project's development volume and reseeds it.

```console
make test       # backend unit/integration, frontend unit, type and lint checks
make e2e        # release image and Playwright browser test
make build      # production image with Vue embedded in FastAPI
make benchmark  # rolled-back 100,000-job reporting benchmark
```

## Commands

The release image exposes one CLI, a web process, and a collector process:

```console
rainstone ingest-fixtures --path fixtures/phase1.json [--path …]
rainstone collect [--cycles N]
rainstone discover [--values values.yaml]
rainstone enroll --shared-account … [--replace-source]
rainstone bootstrap --admin-database-url … --write-dsn …   # optional reader
rainstone wait-ready [--timeout 600]
rainstone mark-installed
rainstone heartbeat [--max-age 300]
rainstone doctor
rainstone catalog validate|import|refresh|coverage [--path …]
uvicorn rainstone.main:app --host 0.0.0.0 --port 8000
```

`make collect`, `make doctor`, `make catalog` and `make chart-lint` run these
against the development environment and lint the packaged chart.

The fixture command is replay-safe. It upserts source facts using stable source
identities, records an ingestion cursor, and keeps the current calculation
when its source-fact and price digest is unchanged.

## Identity contract

Three explicit modes, selected by configuration rather than inferred from a URL
prefix. `development` provides fixture identities through `X-Rainstone-Tenant`,
`X-Rainstone-User` and optional `X-Rainstone-Admin: true`, and is rejected
unless demo mode is enabled. `trusted-proxy` requires those values from a proxy
that strips client copies first. `anvil-workspace` reports one fixed tenant and
shared Galaxy account and rejects any client identity header; the packaged
browser application sends no identity headers outside development mode. Every
detail, table, total, search, invocation, user, infrastructure, status and
export query applies the resolved tenant and owner scope on the backend.
[`docs/deployment.md`](docs/deployment.md) has the deployment contract.

## Cost semantics

- `additional`: known zero for policy-verified baseline capacity; dedicated VM
  lifecycle cost when priced; unknown remains null.
- Work on the already-running Galaxy host adds nothing to the bill, so it is
  reported as $0 extra ("Used your Galaxy server"). The host's cost is shown
  separately as the Galaxy server's cost and is never divided among jobs. This
  is a decision, not a missing policy: a per-job share of the host would change
  nothing a user pays.
- `allocated`: dedicated VM cost. It is unavailable for work on the Galaxy
  host, for the reason above.
- The default reporting mode accrues cost within half-open from/to intervals.
  Minimum-charge uplift is distributed proportionally across the observed
  positive-duration lifetime; untimed costs remain unattributed.
- Partial amounts are known subtotals. Unknown amounts stay blank in CSV and are
  distinct from exact zero. Unsupported currencies are rejected.
- A separately labeled completed-job cohort supplies historical tool statistics;
  its percentiles are never added across workflow steps.

- A resource lifetime is priced once per basis and component, with the provider
  minimum applied once to that lifetime. Retries that reuse one VM share that
  charge instead of repeating it; work shared by two Galaxy jobs becomes
  unavailable pending an allocation policy.

Catalog artifacts fetched from a feed are untrusted until an Ed25519 signature
verifies against a release-pinned key; a feed cannot be configured without one.

Prices come from a signed catalog Rainstone's publisher builds monthly from
Google's Cloud Billing Catalog API: the `t2d`, `n2` and `g2` families
(including the NVIDIA L4 GPUs that come with a G2 machine), on-demand, in US
regions, each rate dated from its price history back to a year before
publication. Installations download it from the feed; a copy observed on
2026-09-30 ships in the image for first start and offline use. Work on a
machine, region or date the catalog does not cover stays visibly unpriced
rather than borrowing another rate. Disks, network, discounts, credits, and
taxes are excluded.

The dashboard leads with the period, the amount and its coverage; periods are
calendar periods, workflow runs report their whole cost beside the selected
period's share, and accounting vocabulary is translated at the presentation
layer. See [`docs/dashboard.md`](docs/dashboard.md).

The adopted design-system revisions are recorded in
[`docs/design-reference.md`](docs/design-reference.md).
The shared filter and accounting contract is documented in
[`docs/reporting-contract.md`](docs/reporting-contract.md), collection and
resource accounting in [`docs/collection.md`](docs/collection.md), and the
measured
100,000-job results and query plan are in
[`docs/benchmark-results.md`](docs/benchmark-results.md).
