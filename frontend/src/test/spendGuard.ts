import type { SpendGuard } from "../api";

export const GUARD: SpendGuard = {
  revision: 0, limit: null, stop_jobs: false, triggered_at: null, source_changed: false, margin: "0.25",
  stale: false, cancellation_checked_at: null, cancellation_error: null, cancellations: [], notifications: [],
  snapshot: { amount: "3.12", hourly_rate: "0", observed_at: "2026-10-21T12:00:00Z",
    coverage_start: "2026-03-03T00:00:00Z", generation: "generation", enrollment: "source",
    data_age_seconds: "0", incomplete_jobs: 0, unpriced_running_resources: 0, gaps: 0 },
};
