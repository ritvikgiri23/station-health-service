# Station Health Service: Architecture & Design

What was built, and how it grows to 100K+ Stations. Capitalised terms are defined in [`CONTEXT.md`](../CONTEXT.md). Decisions: [ADR-0001](adr/0001-tiered-report-storage.md) (tiered storage), [ADR-0002](adr/0002-collector-model-and-silent.md) (Collector model, Silent), [ADR-0003](adr/0003-periodic-scoring-worker.md) (periodic scoring worker). Requirements are in the [spec](station-health-service/spec.md), and exact API behaviour is in the [README](../README.md).

## 1. High-level architecture

```
  Collector ──POST /health-reports──▶ ┌────────────┐            ┌───────────────┐
  (simulator stands in)  ingest key   │  API       │──insert───▶│   MySQL 8     │
  Operators, dashboard ──read key───▶ │  (Flask)   │◀──query────│ stations      │
  Admins ───────────────admin key───▶ └────────────┘            │ health_reports│
                                      ┌────────────┐  read      │ station_health│
                                      │  Worker    │◀──window───│ flag_changes  │
                                      │  every 60s │──upsert───▶│ scoring_runs  │
                                      └────────────┘  changed   │ hourly_summ.  │
                                                                └───────────────┘
```

A NOC **Collector** Probes every Station and writes one Health Report per Probe, whether or not the Station answers (ADR-0002). Only that model explains `connectivity_status: offline`: Offline means the Station did not answer the Probe. A registered Station with no Health Reports in its Scoring Window is **Silent**. That usually means a gap in our monitoring, but it is still Poor Hygiene, because a Station no Probe has reached must never be shown to drivers as working.

There are two processes, from one image. The **API** handles ingest (a plain idempotent insert), queries, the Station Registry and the dashboard. The **worker** runs every 60 s: a scoring run, then hourly summary catch-up, then retention.

**Why a periodic worker (ADR-0003).** Silent is the *absence* of Health Reports, so nothing triggered by a Health Report arriving can detect it. Scoring at read time would aggregate ~1.5M raw rows per query at 100K Stations. Instead, the worker reads the Scoring Window's Health Reports in one query and scores every registered Station through a pure scoring core. It writes only Stations whose score, Silent, Poor Hygiene, Flag Reason or firmware changed, appends Flag Changes, and records the run. Scores can be ~60 s old, so every score response carries `scored_at`. A MySQL named lock (`GET_LOCK`, no wait) means a second worker, for example during a deploy, skips its run rather than duplicating Flag Changes.

## 2. Data model and schema

| Table | Role | Key | Size at 100K Stations |
|---|---|---|---|
| `stations` | Station Registry: Region (nullable), verified | `station_id` | 100K rows |
| `health_reports` | raw Health Reports, 48 h | (`station_id`, `timestamp`); index on `timestamp` | 288M rows, ~58 GB |
| `station_health` | current state per Station: score and parts, p95, report count, Silent, Poor Hygiene, Flag Reason, flagged since, firmware | `station_id`; index (`poor_hygiene`, `flagged_since`) | 100K rows, ~20 MB |
| `flag_changes` | append-only: Station, time, entered/left, Flag Reason, score | id; index (`station_id`, `changed_at`) | ~200–400 MB/year |
| `scoring_runs` | one row: last run time, Stations scored, duration | fixed id | 1 row |
| `hourly_summaries` | per Station per completed hour: report/online counts, avg/max/p95 latency, sum of Error Counts, avg Hygiene Score | (`hour_start`, `station_id`) | 72M rows, ~7 GB at 30 d |

**`health_reports` is deliberately partition-ready (ADR-0001).** It has no foreign key to `stations`, and `timestamp` is part of the primary key. MySQL partitioned tables forbid foreign keys and need the partition column in every unique key. The same key makes Collector retries idempotent. A Health Report for an unregistered Station is stored, and the Station is registered as an **Unverified Station**.

## 3. API design

| Endpoint | Role | Behaviour |
|---|---|---|
| `POST /health-reports` | `ingest` | `201` new; `200` duplicate (first stored wins); `422` invalid, >5 min in the future or >48 h old |
| `GET /stations/{id}/health` | `read` | Region, verified, latest Health Report, Hygiene Score and its parts, Silent, Poor Hygiene, Flag Reason, flagged since, `scored_at`; `404` if not registered and never reported |
| `GET /poor-hygiene` | `read` | `sort` by score (worst first, Silent as 0) or `flagged_since`; filters `region`, `flag_reason`, `verified`; `limit` 50 by default, 500 at most; `total`, `next_cursor`, `scored_at` |
| `GET /metrics` | `read` | fleet snapshot, optional `group_by=region` or `firmware_version` |
| `GET /metrics/trend` | `read` | hourly points over `hours` (default 24), optional `group_by=region` |
| `PUT`, `DELETE /stations/{id}`, `GET /stations` | `admin` | Station Registry; `PUT` is idempotent and marks the Station verified |
| `GET /livez`, `GET /readyz` | none | liveness and readiness (section 11) |

- **"Latest" means the newest `timestamp`**, not arrival order, so a late Health Report counts in its Scoring Window but never replaces the latest snapshot.
- **Cursor paging**: the opaque cursor holds the sort key of the page's last row. Pages stay consistent while scores change every minute, which offsets would not.
- **Errors** have one JSON shape everywhere: `{code, status, message, errors}`.
- **OpenAPI** is generated from the marshmallow schemas that also validate requests, so the docs can't drift from the code. It is served at [`/openapi.json`](http://localhost:8000/openapi.json), with Swagger UI at `/docs`.
- **Metrics** are read from `station_health` and `hourly_summaries`, never from raw Health Reports. Summaries keep no Poor Hygiene history, so each trend point counts the Stations whose average score for that hour is below the Flag Threshold.

## 4. Scoring model

**Hygiene Score = Availability × (0.4 × latency score + 0.6 × error score) × 100**, rounded half up to an integer from 0 to 100, over a 15-minute Scoring Window.

- **Availability** is the share of Health Reports in the window that are not Offline. It *multiplies* the score, so a Station that is often Offline can never score well.
- **Latency score**: 1.0 when the p95 of *online* Health Reports is at or below 150 ms, 0.0 at or above 1000 ms, and linear in between. The p95 catches the spikes that cause failed session starts, which an average would hide. Latency on Offline Health Reports is a timeout and is ignored.
- **Error score**: 1.0 at 0 errors per online Health Report, 0.0 at 3 or more, and linear in between.
- **Weights 0.6 / 0.4**: errors leave drivers unable to charge, so they count most. Latency alone can pull the score down to 60 at worst, which is not below the Flag Threshold.
- A window with **no online Health Reports** scores 0. **Firmware is not scored**; it is kept for diagnosis.

**Flagging.** A Station enters Poor Hygiene when it is Silent or scores below the **Flag Threshold (60)**. It leaves only when it is not Silent, scores at least the **Clear Threshold (70)**, *and* its window holds at least **5 Health Reports**. Flagging is quick; clearing must be earned. The **Flag Reason** is `silent`, or whichever of Availability, latency score and error score is lowest. Each entry and exit appends a Flag Change. Every value is configurable (`.env.example`).

Scenarios behind the defaults, each a named test in `tests/test_scoring.py` or `tests/test_flagging.py`:

| Scenario | Score | Outcome |
|---|---|---|
| Healthy, 15 Health Reports | 100 | not flagged |
| Flapping: 6 of 15 Offline | 60 | at the Flag Threshold. Any more Offline flags `availability`, because Availability multiplies the score |
| Slow but reliable: 800 ms | 69 | not flagged: latency alone does not flag |
| Fast but error-prone: 2 errors per Health Report | 60 | at the threshold. 3 or more errors scores 40 and flags `errors` |
| Slightly degraded: 1 Offline, 300 ms, 0.5 errors | 77 | not flagged |
| Offline all window | 0 | flagged, `availability` |
| Silent: no Health Reports | — | flagged, `silent` |
| Hovering at 58 → 61 → 59 → 62 | — | flagged at 58 and stays flagged (hysteresis) |
| One good Health Report after silence | 100 | no longer Silent, but stays flagged (minimum evidence) |

**Assumptions:**

- The Collector Probes each Station every 60 s, and all sizing is based on this.
- Error Count is errors since the previous Health Report, not a running total; no boot identifier exists that would make a running total reliable.
- Offline means the Station did not answer the Probe.

## 5. Scaling to 100K+ Stations

At 100K Stations that is ~1,700 Health Reports/s: ~144M a day, or ~52 billion (~10 TB) a year. Scoring only needs the last 15 minutes (~1.5M rows).

- **Tiered storage (ADR-0001)**: raw Health Reports for 48 h (~58 GB), hourly summaries for 30 d (~7 GB), daily summaries for 13 months (~40M rows), then an S3/Parquet archive queried with Athena. Only the raw and hourly tiers are built. The 30-day tier is sized for the four-week anomaly baseline. Ingest rejects Health Reports older than raw retention.
- **Daily partitions**: in production `health_reports` is range-partitioned by day. Retention becomes a near-instant `DROP PARTITION`, and window reads touch only recent partitions. Today retention deletes in batches of 10,000 rows.
- **Worker cost**: writes stay small, because few Stations change in any minute. Reading ~1.5M rows per run is the limit. The next step is **incremental aggregation**: per-Station per-minute buckets (counts, error sum, a latency sketch), so each run merges 15 buckets per Station, with Stations sharded across workers by `station_id` hash. After that comes **streaming aggregation** (Managed Flink, or the ingest consumers), which holds windows in memory and emits Flag Changes.
- **p95 at scale**: buckets hold a mergeable **t-digest**, and hourly and daily p95s come from merging digests, never from averaging p95s.
- **Batch ingest**: a batch endpoint (~500 Health Reports per request, with a result for each) using multi-row `INSERT … ON DUPLICATE KEY` removes the per-row round trip and commit. Backfill already uses ingest's validation and storage functions this way.
- **Reads** go to an Aurora read replica. The Poor Hygiene list reads only flagged rows of a 100K-row table.

## 6. Extensions

**Proactive alerting.** Flag Changes are the hook. After each run, a publisher groups that run's Flag Changes by **Region and Flag Reason**, then sends one EventBridge event per group, for example "eu-west: 412 Stations entered Poor Hygiene, `silent`". Rules route by Flag Reason:

- `silent` goes to NOC monitoring, because the fault is usually ours.
- `availability`, `latency` and `errors` go to field-service ticketing.

Grouping turns a regional failure into one alert instead of thousands. Hysteresis and minimum evidence mean a Station hovering near the threshold does not alert again and again.

**Anomaly detection.** A **Station Anomaly** is behaviour that is unusual for a Station against its own history or its peers, even when its Hygiene Score is fine, for example latency doubling from 60 to 120 ms. This is distinct from Poor Hygiene, which uses fixed thresholds. Phase 1 is statistical:

- compare each Station's hour with the same hour-of-week over four weeks of hourly summaries (median and median absolute deviation);
- compare it with peers in the same Region and on the same firmware, which tells a bad firmware release apart from one degraded Station.

Station Anomalies are recorded apart from Flag Changes. Phase 2 adds ML (SageMaker Random Cut Forest) trained on the summary tiers.

**Multi-region redundancy.**

- **First, active-passive**: ECS in two AWS regions, Aurora Global Database (lag under a second, managed failover) and Route 53 failover. Workers score only in the active AWS region.
- **Later, regional cells**: each cell owns a set of Regions end to end, with a thin global layer for fleet-wide metrics.

A failover is a **Monitoring Gap**: for minutes no Health Reports arrive, and every Station would go Silent. The worker detects a Monitoring Gap when intake collapses fleet-wide. It then suppresses Silent Flag Changes during the gap and for one Scoring Window after it, and raises a single Monitoring Gap alert. None of this is built.

## 7. Security

**Built:**

- API keys in `X-API-Key`, mapped to roles that are applied per route: `ingest` for the Collector, `read` for operators and the dashboard, and `admin` for the Station Registry. With least privilege, a leaked Collector key can neither read fleet data nor change the Station Registry.
- Responses are `401` for a missing or unknown key and `403` for the wrong role.
- Strict schemas reject unknown fields.
- The dashboard's demo key must be `read`-only, or the service won't start.

**Production:**

- API Gateway with per-client rate limits and AWS WAF.
- IAM (SigV4) or mTLS for the Collector.
- Cognito federated with company SSO for operators.
- Secrets Manager with rotation.
- TLS everywhere, including to Aurora.
- Least-privilege IAM per ECS task, with the database in private subnets.

## 8. Testing strategy

Tests check externally observable behaviour only. Time is always injected, so no test sleeps or reads the wall clock.

1. **The HTTP API plus "run the worker once at `now`"**, against real MySQL 8 in Testcontainers. Upserts, the named lock and primary-key idempotency are MySQL-specific, so a fake database would test the wrong thing. A test submits Health Reports, runs the worker at a chosen `now`, checks the read APIs, then repeats with a later `now`. This seam covers ingest, auth, Silent, thresholds, paging, metrics, summary catch-up after the worker has been down, retention, concurrent runs, and a valid OpenAPI document.
2. **The pure scoring core** (`scoring.py`): table-driven tests that need no database.

Every design scenario is a named test, including duplicates, late arrival, future timestamps and unregistered Stations. A simulator smoke test checks that each profile yields its expected Flag Reason.

## 9. CI/CD (described, not built)

1. **Pull request**: ruff, `mypy --strict`, pytest with Testcontainers, an image build, and an OpenAPI check: the spec must be valid, and it is diffed against `main` to catch breaking changes.
2. **Merge**:
   - push the image to ECR and deploy to **staging**;
   - run Alembic migrations first, as a one-off ECS task, kept backward-compatible so old and new tasks can run side by side;
   - run smoke tests: `/readyz`, a Health Report round trip, and a scoring run.
3. **Approval**, then **production**: a rolling deploy for the worker (the named lock makes overlap safe) and blue-green for the API, with automatic rollback on CloudWatch alarms.

## 10. AWS mapping

| Concern | Service |
|---|---|
| API and worker | **ECS Fargate**, two services from one image |
| Database | **Aurora MySQL**, Multi-AZ, a read replica for queries, Global Database for multi-region |
| Ingest at 100K+ | **API Gateway → SQS → ECS ingest consumers** doing batch inserts |
| Alerting | **EventBridge** rules routing grouped Flag Changes to SNS, paging and ticketing |
| Archive | **S3/Parquet** with Athena |
| Observability | **CloudWatch**: Logs Insights over the JSON logs, Embedded Metric Format for run metrics, alarms on scoring freshness, SQS queue age and the DLQ |

**Why a queue:** SQS absorbs bursts, such as the Collector replaying its backlog after a Monitoring Gap. Consumers insert at a rate Aurora can sustain, so a slow database shows up as queue age, not as errors returned to the Collector. Bad messages go to the DLQ. Idempotent inserts make at-least-once delivery safe.

**Lambda was rejected**: the scoring run is a stateful batch over the whole fleet every minute. At ~1,700 inserts/s, short-lived functions churn MySQL connections, even behind RDS Proxy. Long-lived Fargate tasks with pooled connections fit better.

## 11. Observability (built)

- **Structured JSON logs**: every line carries a request ID (the caller's `X-Request-ID`, or a generated one), and each request ends with a summary line.
- **`/livez`** reports liveness. **`/readyz`** returns `503` if the database is unreachable. It returns `degraded` (still `200`) if no scoring run has completed yet, or if the last one finished more than 3 minutes ago, so a stuck worker is visible.
- **One log line per scoring run**: Stations scored, rows written, Flag Changes, Silent count and duration. Skipped and failed runs are logged too.

## 12. AI-assisted development

### Validating AI-generated code

_To be written by the author._

### How AI tools influenced architectural decisions

_To be written by the author._

### Trade-offs between AI assistance and manual coding

_To be written by the author._
