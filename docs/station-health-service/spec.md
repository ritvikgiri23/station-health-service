# Spec: Station Health Service

Status: ready-for-agent

Vocabulary follows `CONTEXT.md` (Station, Station Registry, Unverified Station, Region, Collector, Probe, Health Report, Offline, Error Count, Hygiene Score, Availability, Scoring Window, Silent, Monitoring Gap, Poor Hygiene, Flag Threshold, Clear Threshold, Flag Reason, Station Anomaly, Flag Change).

## Problem Statement

The NOC monitors 100K+ EV charging stations. A Collector probes every Station on a schedule and produces Health Reports, but there is nowhere that turns that stream of snapshots into a judgement of which Stations are actually problematic. Operators cannot answer "which stations should we act on right now, and why?", and drivers, via whatever app consumes station status, risk being sent to chargers that look fine in their latest snapshot but have been unreliable, or that have stopped being monitored altogether.

Specific gaps:

- A single Health Report is a poor indicator of a Station's hygiene. A Station that keeps dropping offline and coming back can look healthy in any one report.
- A Station that stops reporting entirely is invisible, even though "we don't know" is never safe to present as "working".
- Operators have no aggregated view (by Region, by firmware) to distinguish a bad firmware release, a regional Collector failure, or individual degraded Stations.
- Raw telemetry volume (~1,700 Health Reports/sec, ~52 billion/year at 100K Stations) makes naive storage unworkable.

## Solution

A Flask microservice backed by MySQL that:

1. **Accepts Health Reports** from the Collector, one per request, idempotently.
2. **Scores each Station over a 15-minute Scoring Window** with a background worker that runs every 60 seconds and computes a Hygiene Score from Availability, p95 latency and errors per online Health Report.
3. **Flags Poor Hygiene** using a Flag Threshold and a higher Clear Threshold, with a minimum-evidence rule for clearing. Treats Silent Stations as Poor Hygiene, and records a Flag Reason and a Flag Change for every transition.
4. **Exposes REST APIs** for a Station's latest health status, the list of Stations with Poor Hygiene, aggregated metrics (current snapshot and hourly trends), and Station Registry management, secured by role-scoped API keys and documented with OpenAPI.
5. **Stores telemetry in tiers.** Raw Health Reports are kept for 48 hours, and hourly summaries are kept for 30 days. The raw table is designed to be partition-ready.
6. Ships with a **scenario-based simulator** (live traffic and bulk backfill), a **one-page dashboard**, structured logging and health/readiness checks, all runnable locally with docker-compose.

From the operator's perspective: the poor-hygiene list shows the worst Stations first, each with a reason, and Stations don't flicker in and out of it. A whole Region going Silent reads clearly as a monitoring problem, not as thousands of broken chargers.

## User Stories

### Ingesting Health Reports

1. As the Collector, I want to submit one Health Report per request containing `station_id`, `timestamp`, `connectivity_status`, `latency_ms`, `error_count` and `firmware_version`, so that every Probe result is recorded.
2. As the Collector, I want resubmitting an identical Health Report (same `station_id` and `timestamp`) to succeed without creating a second record, so that my retries after network failures are safe.
3. As the Collector, I want a clear validation error when a Health Report is malformed (missing fields, wrong types, unknown connectivity status, negative latency or Error Count), so that I can fix the problem at the source.
4. As the Collector, I want Health Reports timestamped more than 5 minutes in the future to be rejected, so that a Station with a wrong clock cannot pin its "latest" status indefinitely.
5. As the Collector, I want Health Reports older than the 48-hour raw retention to be rejected, so that I am not told data was stored when it would be discarded immediately.
6. As the Collector, I want Health Reports that arrive late or out of order to still be stored and counted in their Scoring Window, so that a backlog does not corrupt Availability.
7. As the Collector, I want to submit Health Reports for a Station that is not yet in the Station Registry and have them accepted, so that newly installed Stations are monitored from their first Probe.
8. As an operator, I want a Station first seen through a Health Report to be registered automatically as an Unverified Station with no Region, so that no real data is lost and possible bad IDs stay visible and labelled.
9. As the Collector, I want to authenticate with an API key that only grants the ingest role, so that a leaked Collector key cannot read fleet data or modify the Station Registry.
10. As a security reviewer, I want requests with no API key to be rejected as unauthenticated, and requests with a key lacking the required role to be rejected as forbidden, so that least privilege is enforced.

### Scoring and flagging

11. As an operator, I want each Station's Hygiene Score computed from all its Health Reports in the last 15 minutes rather than from its latest report alone, so that intermittently failing Stations are caught.
12. As an operator, I want the Scoring Window length to be configurable, so that it can be tuned without code changes.
13. As an operator, I want Availability to be the share of a Station's Health Reports in the Scoring Window that are not Offline, so that frequent Offline Probes drive the score down.
14. As an operator, I want the Hygiene Score to be Availability multiplied by a weighted blend of the latency score and the error score, so that a Station that is often offline can never score well however good it is when online.
15. As an operator, I want the latency score derived from the p95 latency of the Station's online Health Reports in the window, so that latency spikes, which cause failed session starts, are not hidden by averages.
16. As an operator, I want the latency score to fall linearly from 1.0 at or below 150 ms to 0.0 at or above 1000 ms, with both limits configurable, so that the scoring is explainable and tunable.
17. As an operator, I want latency on Offline Health Reports ignored, so that meaningless timeout values do not distort the score.
18. As an operator, I want the error score derived from errors per online Health Report in the window, so that Stations are compared fairly regardless of how much of the window they were online.
19. As an operator, I want the error score to fall linearly from 1.0 at 0 errors per online Health Report to 0.0 at 3 or more, with the limit configurable, so that the scoring is explainable and tunable.
20. As an operator, I want errors weighted 60% and latency 40% within the quality blend, with both weights configurable, so that the failures that leave drivers unable to charge count most.
21. As an operator, I want firmware version excluded from the Hygiene Score, so that the score measures behaviour, and firmware is available for diagnosis instead.
22. As an operator, I want a Station to enter Poor Hygiene when its Hygiene Score falls below the Flag Threshold (default 60), so that degraded Stations are surfaced.
23. As an operator, I want a flagged Station to leave Poor Hygiene only when its score reaches the Clear Threshold (default 70), so that Stations hovering near the threshold do not flicker in and out of the list.
24. As an operator, I want a flagged Station to leave Poor Hygiene only when its Scoring Window also holds at least 5 Health Reports (configurable), so that a single good report after a long silence does not prematurely declare it healthy.
25. As a driver, I want a Station that has gone Silent to be treated as Poor Hygiene, so that I am never sent to a charger nobody has been able to check.
26. As an operator, I want a registered Station that has never reported to be Silent, so that newly installed but never-connected chargers are caught.
27. As an operator, I want a Silent Station to stop being Silent as soon as Health Reports arrive again, while still being subject to the Clear Threshold and minimum-evidence rule before leaving Poor Hygiene, so that recovery is detected promptly but has to be demonstrated.
28. As an operator, I want every Station with Poor Hygiene to carry a Flag Reason (Silent, or whichever of Availability, latency or errors scored worst), so that I know what kind of fix to dispatch.
29. As an operator, I want a Flag Change recorded each time a Station enters or leaves Poor Hygiene, with the time, the direction and the Flag Reason, so that I can see how long Stations have been flagged and alerting can be built on it later.
30. As an operator, I want each flagged Station's "flagged since" time to be available, so that I can find long-neglected problems.
31. As an operator, I want scores recalculated every 60 seconds by a background worker, so that Silent Stations are detected even though no Health Report triggers it.
32. As an operator, I want only one scoring run to execute at a time even if two worker processes are running (e.g., during a deploy), so that Flag Changes are not duplicated.
33. As an operator, I want each scoring run to write only Stations whose visible state changed, so that the database is not rewritten 100K rows per minute.
34. As an operator, I want the time of the last completed scoring run recorded, along with how many Stations were scored and how long it took, so that score freshness is always knowable.

### Querying Station health

35. As an operator, I want to retrieve a Station's latest health status, including its latest Health Report (by newest timestamp, not arrival order), so that I see the current snapshot.
36. As an operator, I want the same response to include the Hygiene Score, Availability, latency score and error score, Silent, Poor Hygiene, Flag Reason and "flagged since", so that I see both what's happening now and why it was judged that way.
37. As an operator, I want the response to include when the score was last computed, so that I (and any app consuming it) can tell whether it's fresh.
38. As an operator, I want the response to include the Station's Region and whether it is an Unverified Station, so that I have its registry context.
39. As an operator, I want a clear not-found response for a Station that is neither registered nor has ever reported, so that typos are obvious.

### Listing Stations with Poor Hygiene

40. As an operator, I want to list all Stations with Poor Hygiene, worst score first, with Silent Stations treated as score 0 and ties broken by oldest "flagged since", so that the most urgent problems are at the top.
41. As an operator, I want to optionally sort the list by "flagged since", so that I can review longest-standing or newest problems.
42. As an operator, I want to filter the list by Region, Flag Reason and verified/unverified, so that I can focus on one area, one kind of problem, or registry clean-up.
43. As an operator, I want the list paged with a cursor (default 50 per page, maximum 500), so that pages stay consistent while scores change every minute.
44. As an operator, I want the list to report the total number of matching Stations, so that I can gauge an incident's size at a glance.

### Aggregated metrics

45. As an operator, I want a current fleet-wide snapshot of station count, Poor Hygiene count and percentage, Silent count, Unverified Station count, average Hygiene Score, average Availability and average p95 latency, so that I understand overall network health.
46. As an operator, I want the same snapshot grouped by Region, with Stations that have no Region grouped as "unassigned", so that I can tell a regional problem from a fleet-wide one.
47. As an operator, I want the same snapshot grouped by firmware version, so that I can spot a bad firmware release across many Stations.
48. As an operator, I want hourly trends of those metrics over a requested number of past hours, optionally grouped by Region, so that I can see whether things are getting worse.
49. As an operator, I want metrics served from precomputed state and hourly summaries rather than raw Health Reports, so that they stay fast at 100K Stations.

### Station Registry

50. As an admin, I want to register or update a Station with its Region, which also marks it verified, so that the Station Registry reflects real inventory.
51. As an admin, I want to confirm an Unverified Station by registering it, so that it stops appearing as unverified.
52. As an admin, I want to delete a Station from the Station Registry, so that bad IDs stop appearing as Silent forever.
53. As an admin, I want to list Stations, filterable to Unverified Stations only, so that I can work through registry clean-up.
54. As an admin, I want registry changes restricted to the admin role, so that the Collector and read-only users cannot change inventory.
55. As a reviewer, I want a seed command that loads a set of Stations with Regions, so that the system has a realistic registry to run against.

### Storage lifecycle

56. As an operator, I want raw Health Reports older than 48 hours removed automatically, so that the raw table stays bounded.
57. As an operator, I want hourly per-Station summaries built for each completed hour (report count, online count, average and maximum latency, p95 latency, total errors, average Hygiene Score), so that trends survive raw retention.
58. As an operator, I want the worker to build summaries for any completed hour within raw retention that does not yet have one, so that the system catches up by itself after the worker has been down, and backfilled history gets summarised.
59. As an operator, I want hourly summaries older than 30 days removed automatically, so that the summary table stays bounded.

### Operability

60. As an operator, I want a liveness check that reports whether the service process is up, so that the container orchestrator can restart it.
61. As an operator, I want a readiness check that fails when the database is unreachable and reports degraded when the last scoring run is older than about 3 minutes, so that a stuck worker is noticed rather than silently serving old scores.
62. As an operator, I want structured JSON logs with a request ID and the `station_id` where relevant, so that I can search logs effectively.
63. As an operator, I want the worker to log one summary line per scoring run (Stations scored, Flag Changes, Silent count, duration), so that run health is visible without a metrics stack.
64. As a developer, I want all thresholds, weights, window length, retention periods and API keys supplied through environment configuration, with a documented example file, so that behaviour can be tuned without code changes.

### API documentation

65. As an API consumer, I want an OpenAPI specification and Swagger UI generated from the same schemas that validate requests, so that the documentation can't drift from behaviour.
66. As an API consumer, I want the API-key security scheme described in the OpenAPI spec, so that I can authenticate from Swagger UI.

### Simulator and demo

67. As a reviewer, I want a simulator that plays the Collector for N Stations, sending one Health Report per Station per simulated minute, so that the system can be seen working without a real Collector.
68. As a reviewer, I want the simulator to assign Stations to scenario profiles (healthy, flapping, slow, error-prone, goes Silent, unregistered ID), so that each scoring rule is visibly exercised.
69. As a reviewer, I want a speed multiplier on the simulator, so that the Scoring Window fills in seconds rather than 15 minutes.
70. As a reviewer, I want a backfill command that bulk-loads the last 24 hours of Health Reports through the service's own validation and storage logic, so that trends show data immediately.
71. As a reviewer, I want the simulator runnable as an optional docker-compose profile, so that the default startup stays minimal.

### Dashboard

72. As an operator, I want a single dashboard page served by the service, showing summary tiles, the Poor Hygiene list with Flag Reasons, and a 24-hour trend chart, so that fleet state is visible at a glance.
73. As a reviewer, I want the dashboard to work locally using a read-only demo key, so that no extra setup is needed.

### Running locally

74. As a reviewer, I want to start the API, worker and MySQL with one docker-compose command, so that I can run the system in minutes.
75. As a reviewer, I want database migrations applied as part of startup or with one documented command, so that the schema is always current.
76. As a reviewer, I want a README with setup, run, test, seed, simulate and backfill instructions, so that I can evaluate the submission without guesswork.

## Implementation Decisions

### Stack

- Python 3.12, Flask, flask-smorest (blueprints with OpenAPI and Swagger UI), marshmallow (validation and serialisation), SQLAlchemy 2.0, Flask-Migrate (Alembic), PyMySQL, MySQL 8. Everything runs under docker-compose.
- Local tooling: ruff, mypy, pytest. Pinned dependencies. Configuration comes from environment variables, with a documented example file.

### Processes

- **API process:** receives Health Reports (insert only, no scoring), serves queries and registry management.
- **Worker process:** the same codebase and image, a different entrypoint. It loops every 60 seconds and performs a scoring run, catch-up of hourly summaries, and retention clean-up.
- A scoring run takes a MySQL named lock and skips if the lock is held, so concurrent workers are safe.
- The worker exposes a single **"run once at time `now`"** entry point and receives its clock from outside. Its scheduling loop is a thin wrapper around that entry point. This is the main test seam.

### Modules (organised by feature, with a pure core)

- **Scoring core (pure, no I/O):**
  - Inputs: one Station's Health Reports in the Scoring Window, its previous flag state (Poor Hygiene or not, "flagged since"), the current time, and the scoring configuration (window length, latency limits, error limit, weights, Flag Threshold, Clear Threshold, minimum reports to clear).
  - Outputs: Availability, latency score, error score, Hygiene Score (integer 0–100), Silent, Poor Hygiene, Flag Reason, and whether a Flag Change occurred (and in which direction).
  - Also computes p95 latency over online Health Reports.
  - Silent is decided as "no Health Reports in the window" for a registered Station.
- **Reports:** the ingest endpoint, payload schema and validation, idempotent insert, and the automatic registration of Unverified Stations. The validation and storage functions are shared with the simulator's backfill.
- **Stations:** Station Registry endpoints and storage.
- **Health:** Station health status endpoint and the poor-hygiene list endpoint.
- **Metrics:** snapshot and trend endpoints.
- **Worker:** the scoring run (one grouped read of the window → the scoring core for each Station → bulk upsert of changed Station health → appending Flag Changes → updating the scoring-run record), hourly summary catch-up, and retention.
- **Auth:** API-key verification mapped to roles `ingest`, `read` and `admin`, applied per route. Keys come from configuration.
- **Simulator:** scenario profiles, live mode with a speed multiplier, and backfill mode.
- **Dashboard:** one static page served by the API that uses the public read endpoints.

### Scoring formula

- Hygiene Score = Availability × (w_L × latency score + w_E × error score) × 100, rounded to an integer. Defaults: w_L = 0.4, w_E = 0.6.
- Availability = Health Reports that are not Offline ÷ all Health Reports in the window.
- Latency score = linear from 1.0 at p95 ≤ 150 ms to 0.0 at p95 ≥ 1000 ms. The p95 is taken over online Health Reports only.
- Error score = linear from 1.0 at 0 errors per online Health Report to 0.0 at ≥ 3.
- If there are no online Health Reports, Availability is 0, and the Hygiene Score is 0 whatever the other scores are.
- Flag Reason for a scored Station = whichever of Availability, latency score or error score is lowest. For a Silent Station it is `silent`.
- Transitions:
  - Not flagged → flagged when Silent, or when score < Flag Threshold.
  - Flagged → not flagged only when not Silent, score ≥ Clear Threshold, and the window holds at least the minimum number of Health Reports (default 5).
- Error Count means errors since the previous Health Report. It is a documented assumption, not a running total.

### Schema (logical)

- **Station:** `station_id` (primary key), Region (nullable), verified flag, created/updated timestamps.
- **Health Report:** `station_id`, `timestamp`, connectivity status, latency, Error Count, firmware version, received-at time.
  - Primary key is (`station_id`, `timestamp`), which gives idempotency and makes the table partition-ready.
  - Secondary index on `timestamp` for window and retention queries.
  - **No foreign key to Station**, deliberately, so the table can be partitioned later (MySQL partitioned tables cannot have foreign keys).
- **Station health (current state, one row per Station):**
  - Hygiene Score, Availability, latency score, error score, p95 latency, report count in window, Silent, Poor Hygiene, Flag Reason, "flagged since", latest firmware version.
  - Index supporting the poor-hygiene list ordering and filters.
- **Flag Change:** append-only. `station_id`, time, direction (entered or left Poor Hygiene), Flag Reason, score at the time.
- **Scoring run:** a single row holding last completed run time, Stations scored, duration.
- **Hourly summary:** one row per (`station_id`, hour) holding report count, online count, average, maximum and p95 latency, total errors, and average Hygiene Score.

### API contracts

- **Ingest a Health Report** (role `ingest`):
  - New report → 201.
  - Duplicate (same `station_id` and `timestamp`) → 200, with nothing stored a second time.
  - Validation failure, a timestamp more than 5 minutes in the future, or a timestamp older than 48 hours → 422.
- **Get a Station's health** (role `read`):
  - Returns `station_id`, Region, verified, the latest Health Report (newest `timestamp`), and a hygiene block (score, Availability, latency score, error score, Silent, Poor Hygiene, flagged since, Flag Reason).
  - Also returns a `scored_at` value taken from the scoring-run record.
  - 404 if the Station is unknown.
- **List Stations with Poor Hygiene** (role `read`):
  - Sorted by score ascending (Silent = 0), with ties broken by "flagged since" ascending. An optional sort by "flagged since".
  - Filters for Region, Flag Reason and verified.
  - Cursor paging: default 50 per page, maximum 500, with an opaque cursor that encodes the sort key.
  - Response includes the total count and `scored_at`.
- **Metrics snapshot** (role `read`):
  - Optional grouping by Region or by firmware version. Stations without a Region are grouped as "unassigned".
  - Returns station count, Poor Hygiene count and percentage, Silent count, unverified count, average score, average Availability and average p95 latency.
- **Metrics trend** (role `read`):
  - Takes the number of past hours, with an optional grouping by Region.
  - Returns hourly data points built from hourly summaries.
- **Station Registry** (role `admin`):
  - Register or update a Station, idempotently, by `station_id`. Doing so sets it verified.
  - Delete a Station.
  - List Stations, with an optional filter for unverified.
- **Health checks** (no auth):
  - Liveness.
  - Readiness: checks the database, and reports degraded if the last scoring run is older than about 3 minutes.
- All errors use one consistent JSON error shape, and the OpenAPI spec is generated from the same schemas.

### Worker behaviour

- **Scoring run:**
  1. Read all Health Reports with `timestamp` in (now − window, now], grouped by Station.
  2. Load the Station Registry and the current Station health.
  3. Score each registered Station through the core. A registered Station with no Health Reports in the window is Silent.
  4. Upsert only rows whose visible state changed.
  5. Append Flag Changes.
  6. Update the scoring-run record.
- **Summary catch-up:** for each completed hour within raw retention that has no summary, compute and insert one row per (`station_id`, hour).
- **Retention:** delete raw Health Reports older than 48 hours, and hourly summaries older than 30 days, in bounded batches. Partition dropping is described as the production approach.

### Simulator

- Live mode sends Health Reports through the HTTP API using an ingest key.
- Backfill mode calls the service's own validation and storage functions directly with batched inserts, and then relies on the worker's summary catch-up.
- Profiles produce predictable Flag Reasons: flapping → Availability, slow → latency, error-prone → errors, goes Silent → silent, unregistered ID → Unverified Station.

### Architectural decisions recorded elsewhere

- ADR-0001 (tiered Health Report storage), ADR-0002 (Health Reports come from a Collector; Silent means Poor Hygiene) and ADR-0003 (Hygiene Scores computed by a periodic worker) in `docs/adr/`. Where they differ from this summary, the ADRs take precedence.
- The design doc (separate deliverable) covers:
  - AWS mapping: ECS Fargate for the API and worker, Aurora MySQL with a read replica, and API Gateway → SQS → ECS ingest consumers at 100K+ Stations.
  - Proactive alerting: Flag Changes grouped by Region and Flag Reason, routed by Flag Reason, through EventBridge.
  - Anomaly detection: each Station compared with its own history and with its peers, with ML later.
  - Multi-region: active-passive with Aurora Global Database first, then regional cells, with Silent suppressed during a Monitoring Gap.
  - Production authentication, CI/CD, and partitioning and archive details.

## Testing Decisions

### What makes a good test here

- Tests check **externally observable behaviour** only: HTTP responses, and results from the pure scoring core. They never inspect tables directly or check internal function calls.
- Every scenario we discussed during design becomes a named test case before the code is written: flapping, slow but reliable, fast but error-prone, slightly degraded, offline all window, Silent, hovering at 58/61/59/62, recovery after silence with one report, duplicates, late arrival, future timestamp, and unregistered Station.
- Time is always injected. No test sleeps or depends on the wall clock.

### Seam 1 (main): the HTTP API plus "run the worker once at `now`"

- Real Flask app against real MySQL 8 started by Testcontainers, so MySQL-specific behaviour is exercised: upserts, the named lock, window functions, and primary-key idempotency.
- Pattern: submit Health Reports through the API → run the worker once at a chosen `now` → check results through the read APIs. Repeat with later `now` values to observe transitions.
- Covers:
  - ingest validation and idempotency, and late, future and too-old reports
  - automatic registration of Unverified Stations
  - auth (401 without a key, 403 for the wrong role)
  - Silent detection, including registered Stations that never reported
  - the Flag and Clear Thresholds, and the minimum-evidence rule to clear
  - Flag Change ordering and "flagged since"
  - the scoring-run freshness value in responses, and the readiness check reporting degraded when it is stale
  - poor-hygiene ordering, filters, cursor paging and total count
  - metrics grouping, including "unassigned"
  - summary catch-up after a simulated worker outage, and trend output
  - retention clean-up
  - registry create, update, verify, delete and list
  - concurrent scoring runs not duplicating Flag Changes
- A check that the generated OpenAPI document is valid.
- A smoke test that the simulator's profiles, run against the API for a simulated window, produce the expected Flag Reasons.

### Seam 2: the pure scoring core

- Table-driven unit tests with no database: the inputs are a window of Health Reports, the previous flag state, `now` and the configuration, and the outputs are compared with expected scores and states.
- Covers:
  - the Availability calculation
  - p95 over online Health Reports only
  - the linear latency and error scores, including their limits and clamping
  - the weighting
  - zero online Health Reports
  - Flag Reason selection, including ties
  - hysteresis between the Flag Threshold and Clear Threshold
  - the minimum-evidence rule to clear
  - Silent

### Prior art

- None. The repository is new. These two seams set the pattern for any future tests.

## Out of Scope

- Building the Collector itself. The simulator stands in for it.
- A batch ingest endpoint and an SQS ingest pipeline (design doc only).
- Partitioning the raw Health Report table, the daily summary tier and the S3/Parquet archive (design doc only, though the schema is partition-ready).
- JWT/OAuth2, Cognito, mTLS, Secrets Manager and rate limiting (design doc only).
- CI/CD pipelines of any kind (design doc only).
- Proactive alerting delivery, anomaly detection, multi-region deployment and Monitoring Gap suppression (design doc only).
- A Prometheus metrics endpoint.
- Bulk import of Station inventory.
- Scoring firmware version.
- A running-total interpretation of Error Count, or a `boot_id` field, or any fields beyond the six specified in the brief.
- A React frontend.
- Documentation of AI tool usage, which the author owns separately.

## Further Notes

- Documented assumptions:
  - The Collector polls every 60 seconds, and all sizing is based on this.
  - Error Count is errors since the previous Health Report.
  - Offline means the Collector's Probe failed.
  - Silent usually means a gap in monitoring rather than a Station fault.
- Order to build in, given the one-day budget: scoring core → ingest → worker scoring run → health and poor-hygiene endpoints → registry → metrics snapshot → hourly summaries and trend → simulator and backfill → readiness and logging → dashboard (the first thing to drop if time runs short).
- Sizing at 100K Stations, for reference:
  - raw Health Reports: ~288M rows / ~58 GB at 48h retention
  - Station health: ~100K rows / ~20 MB
  - hourly summaries: ~72M rows / ~7 GB at 30 days
  - Flag Changes: ~200–400 MB/year
- Default values (all configurable):

  | Setting | Default |
  |---|---|
  | Scoring Window | 15 min |
  | Worker interval | 60 s |
  | Flag Threshold | 60 |
  | Clear Threshold | 70 |
  | Minimum reports to clear | 5 |
  | Latency limits | 150 / 1000 ms |
  | Error limit | 3 per online Health Report |
  | Weights | 0.4 / 0.6 |
  | Raw retention | 48 h |
  | Summary retention | 30 d |
  | Future-timestamp tolerance | 5 min |
  | Stale-score threshold | ~3 min |
