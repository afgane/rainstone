# Rainstone reporting benchmark

- Generated jobs: 10,000 (transaction rolled back)
- Host: Linux-7.0.12-linuxkit-aarch64-with-glibc2.41 · aarch64 · Python 3.12.11
- PostgreSQL URL host: postgres
- Corpus generation: 28.31 s
- Query: runner=gcp_batch, search=benchmark/tool/3 (1,000 matching jobs), amount sort
- Eight iterations; first is cold with respect to application objects, later runs are warm.
- The corpus is loaded with the report-generation triggers suspended inside the rolled-back transaction: this measures report latency, not ingestion. Those triggers add one small upsert per write statement, so bulk backfill favors batched writes.

| Request | Cold | Warm p50 | Warm p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| summary | 178.3 ms | 137.1 ms | 149.1 ms | 178.3 ms |
| first_page | 134.6 ms | 135.8 ms | 160.2 ms | 160.2 ms |
| deep_page | 135.1 ms | 150.2 ms | 155.4 ms | 155.4 ms |

## Workflow run requests (500 runs)

- Runs group the same corpus: sizes cycle through 1 to 30 jobs and every tenth large run has a nested child workflow.
- `invocations_*` request 20 runs of the 90-day period (`invocations_deep_page` the last page); `breakdown_90_days` and `timeline_day_90_days` cover 90 days; `timeline_hour_2_days` covers the last two days by hour.
- Every request also computes the list's totals and the sidebar's option counts, because each run endpoint answers from one matching set.

| Request | Cold | Warm p50 | Warm p95 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| invocations_first_page | 524.8 ms | 496.7 ms | 530.9 ms | 530.9 ms |
| invocations_deep_page | 520.9 ms | 501.4 ms | 527.4 ms | 527.4 ms |
| breakdown_90_days | 510.4 ms | 504.4 ms | 519.7 ms | 519.7 ms |
| timeline_hour_2_days | 519.7 ms | 542.1 ms | 570.1 ms | 570.1 ms |
| timeline_day_90_days | 531.5 ms | 549.4 ms | 577.3 ms | 577.3 ms |

Target: ordinary interactive requests below 1,000 ms at this size.

The target is sized for a medium deployment: 10,000 jobs and 500 workflow runs,
each request under one second. Every request meets it.

## Larger deployments

The workflow run requests read the facts of every job that belongs to a run and
roll them up per request, so their time follows the jobs in runs, at about
100 ms per 1,000 (`--jobs 100000 --runs 5000` puts about 52,000 jobs in runs).
Measured once at that size, warm p50: the job requests took about 1.5 s and each
of the five run requests about 6 s, whatever the period, because the two-day
hourly timeline reads the same jobs as the 90-day ones. Reading rows instead of
entities, and only for jobs in runs, roughly halved that. Going lower would mean
keeping the loaded facts per calculation revision, or storing a per-job
summary, which is a schema change; neither is done, because a medium deployment
does not need it.

## Representative database plan

The leading-wildcard shared search uses a sequential scan at this scale; total request time above also includes authorization, cost-line loading, aggregation, stable sorting, and serialization.

```text
Aggregate  (cost=401.15..401.16 rows=1 width=8) (actual time=15.192..15.194 rows=1 loops=1)
  Buffers: shared hit=215
  ->  Hash Join  (cost=1.07..398.65 rows=1002 width=0) (actual time=0.043..15.146 rows=1000 loops=1)
        Hash Cond: (job.owner_id = owner.id)
        Join Filter: (((job.source_id)::text ~~* '%benchmark/tool/3%'::text) OR ((job.tool_id)::text ~~* '%benchmark/tool/3%'::text) OR ((COALESCE(job.tool_version, ''::character varying))::text ~~* '%benchmark/tool/3%'::text) OR ((owner.label)::text ~~* '%benchmark/tool/3%'::text))
        Rows Removed by Join Filter: 9008
        Buffers: shared hit=215
        ->  Seq Scan on job  (cost=0.00..364.25 rows=10008 width=53) (actual time=0.008..1.384 rows=10008 loops=1)
              Filter: ((tenant_id = 'fa96280f-b720-5125-adee-f68e69818402'::uuid) AND ((runner)::text = 'gcp_batch'::text))
              Rows Removed by Filter: 9
              Buffers: shared hit=214
        ->  Hash  (cost=1.03..1.03 rows=3 width=33) (actual time=0.007..0.008 rows=3 loops=1)
              Buckets: 1024  Batches: 1  Memory Usage: 9kB
              Buffers: shared hit=1
              ->  Seq Scan on owner  (cost=0.00..1.03 rows=3 width=33) (actual time=0.001..0.002 rows=3 loops=1)
                    Buffers: shared hit=1
Planning:
  Buffers: shared hit=7
Planning Time: 0.290 ms
Execution Time: 15.227 ms
```
