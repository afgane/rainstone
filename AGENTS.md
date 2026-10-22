# Rainstone

Rainstone reports the estimated compute cost of work already performed in
Galaxy. On single-user AnVIL deployments it can also enforce a user-set,
best-effort limit on estimated Batch compute. The collector controls only
Batch jobs through Galaxy; host shutdown remains out of scope.
[`README.md`](README.md) covers what it collects and how costs are
computed; [`docs/`](docs) holds the contracts and design decisions.

## Who it is for

The reader is a domain scientist who wants to know what their analyses cost in
compute. They run whatever analysis their research requires. Cost is context
for them, not a lever, and this is not a cloud pricing console.

- Answer "what did my work cost?" on screen by default, with no configuration.
  Filtering and drill-down exist but stay out of the way.
- Report cost without steering scientific choices. A user-set Batch ceiling
  is the explicit exception: pause Batch dispatch and, if selected, stop
  outstanding Batch jobs. Never activate a limit without the user setting
  one. Keep Galaxy control credentials in the collector alone.
- No "cheaper alternative" hints, efficiency
  scores, or comparisons that imply a tool or workflow choice was wrong.
- Keep cognitive overhead low: few numbers, plain words, one obvious next
  step. If a figure needs an explanation of pricing to make sense, leave it out.
- Accounting vocabulary is translated at the presentation layer
  ([`frontend/src/vocabulary.ts`](frontend/src/vocabulary.ts),
  [`docs/dashboard.md`](docs/dashboard.md)). Do not show internal terms.

## Honesty about cost

- Amounts show two decimals, "less than $0.01" for a real sub-cent cost, and
  "Not available" is never shown as $0.00.
- Anything that leaves out unpriced work says so ("recorded so far", "N jobs
  need cost data"). Sums, averages and extremes exclude incomplete costs and
  say how many were excluded.
- A workflow run's headline is its whole-run total; the selected period's share
  is shown beside it. Never add the two together or mix them in one figure.
- Figures reconcile with Overview wherever they describe the same jobs. The
  Workflow runs page counts only jobs that belong to a workflow run, and users
  also run individual tools, so its total is expected to be lower than the
  Overview headline for the same period. That difference is the cost of jobs
  run outside a workflow, not a discrepancy to fix.
- Costs are compute only, in USD. Historical statistics describe past jobs and
  are never worded as a prediction.
- Jobs on the already-running Galaxy host show $0 extra ("Used your Galaxy
  server"), and the host's cost is shown once, as the server's. Never divide
  the host's cost among jobs or treat a missing host allocation policy as work
  to do; it is a deliberate decision.

## Development

Docker with Compose is the only host dependency. Use the `Makefile` targets;
for one-off checks use `docker compose run --rm --no-deps <service> ...` so
Compose does not recreate the running services.

- `make test` runs backend unit and integration tests and the frontend unit,
  type and lint checks. `make e2e` runs the Playwright browser test.
- Backend: FastAPI, SQLAlchemy and Alembic under `backend/rainstone`. Every
  query applies the resolved tenant and owner scope; a new endpoint must too.
- Frontend: Vue 3, TypeScript and Vite under `frontend`. Dependencies are
  pinned to exact versions, and there is no chart library; add one
  deliberately, not incidentally.
- The API shapes in [`frontend/src/api.ts`](frontend/src/api.ts) mirror
  [`docs/reporting-contract.md`](docs/reporting-contract.md). Change them
  together.
- Report state lives in the URL. A link must reproduce a view, and browser
  history and keyboard operation must keep working.

## Accessibility

Atkinson Hyperlegible, visible focus, textual labels instead of colour alone,
and reduced-motion support are part of the adopted design system
([`docs/design-reference.md`](docs/design-reference.md)). Every chart needs a
text or table alternative and must not rely on colour to carry meaning.

## Conventions

- Names are complete words, as short as they can be while staying specific.
- Comments explain why something non-obvious is done, never what a name says.
- Documentation lines stay within 80 characters. Keep the README to the
  default deployment; put optional configuration in `docs/`.
- Planning notes, investigations and other working files go in `ea-no-commit/`
  at the repository root, which is git-ignored. Do not commit them.
