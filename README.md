# Station Health Service

A Flask microservice that ingests Health Reports from the NOC Collector and judges each EV charging Station's network hygiene. See `docs/station-health-service/spec.md` for the full spec, `CONTEXT.md` for the domain vocabulary, and `docs/adr/` for the architectural decisions.

## Prerequisites

- **Docker** with Compose v2: Docker Desktop, OrbStack, or colima (`brew install colima docker docker-compose && colima start`). Docker runs the service and MySQL, and the test suite uses it through Testcontainers.
- **[uv](https://docs.astral.sh/uv/)** (`brew install uv`) for local development. It installs Python 3.12 and the pinned dependencies from `uv.lock`.
- `make`

## Run

```sh
make up        # docker compose up --build -d
```

This builds the image, starts MySQL 8, the API and the worker, and applies database migrations (`flask db upgrade`) before the API starts serving. The worker is the same image running `python -m station_health.worker`: every 60 seconds (`WORKER_INTERVAL_SECONDS`) it performs a scoring run, catches up hourly summaries and applies retention (see [Hourly summaries and retention](#hourly-summaries-and-retention)). A scoring run takes a MySQL named lock and skips if another worker holds it, so running two workers (e.g. during a deploy) never duplicates Flag Changes. Each run logs one line with Stations scored, Flag Changes, the Silent count and duration. Once it is up:

| URL | What |
|---|---|
| http://localhost:8000/dashboard | [Dashboard](#dashboard): fleet summary, 24-hour trend, Poor Hygiene list |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/openapi.json | Generated OpenAPI document |
| http://localhost:8000/livez | Liveness: `200` while the process is up |
| http://localhost:8000/readyz | Readiness: `503` when the database is unreachable; otherwise `200`, with status `degraded` when the last scoring run is older than 3 minutes (`SCORING_STALE_AFTER_SECONDS`) or there has been none |

Other targets: `make logs` (follow API and worker logs), `make simulate` (start the [simulator](#simulator)), `make backfill` (load past Health Reports, see [Backfill](#backfill)), `make migrate` (re-apply migrations in the running container), `make down` (stop; `docker compose down -v` also drops the database volume).

### Try it

```sh
curl -i -X POST localhost:8000/health-reports \
  -H 'X-API-Key: dev-ingest-key' -H 'Content-Type: application/json' \
  -d "{\"station_id\": \"ST-0001\", \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",
       \"connectivity_status\": \"online\", \"latency_ms\": 120, \"error_count\": 0,
       \"firmware_version\": \"1.4.2\"}"
```

A new Health Report returns `201`. Sending the same `station_id` and `timestamp` again returns `200`, and nothing is stored a second time. A Station that isn't in the Station Registry yet is registered as an Unverified Station with no Region. See it with `curl localhost:8000/stations/ST-0001 -H 'X-API-Key: dev-admin-key'`.

Ingest assumptions:
- `timestamp` must include a timezone offset (for example `Z` or `+05:30`). It is stored and returned in UTC, so the same instant written with different offsets is the same Health Report.
- When a second Health Report arrives with the same `station_id` and `timestamp`, the first one wins. The `200` response returns the stored Health Report.
- Only the six specified fields are accepted. An unknown field gets `422`, so that typos aren't silently dropped.
- A body that isn't valid JSON gets `400`. A JSON body that fails validation gets `422`.

### Scoring and Station health

The worker scores every registered Station from its Health Reports in the Scoring Window, the last 15 minutes (`SCORING_WINDOW_MINUTES`), read in one grouped query:

- **Availability**: the share of Health Reports in the window that are not Offline.
- **Latency score**: from the p95 latency of online Health Reports only. It is 1.0 at or below 150 ms, 0.0 at or above 1000 ms, and linear in between. The p95 uses nearest rank, so it is always an observed latency. With 15 Health Reports per window, that is the slowest one.
- **Error score**: from errors per online Health Report (Error Count summed over online Health Reports only). It is 1.0 at 0 and 0.0 at 3 or more.
- **Hygiene Score** = Availability × (0.4 × latency score + 0.6 × error score) × 100, rounded half up. A Station with no online Health Reports in the window scores 0, and its latency and error scores are `null` because nothing was measured.

Each run then decides whether each Station has **Poor Hygiene**:

- A Station with no Health Reports in its window is **Silent**. A Silent Station always has Poor Hygiene, with Flag Reason `silent`, and its score and score parts are `null`.
- A Station enters Poor Hygiene when its Hygiene Score is below the Flag Threshold (60).
- It leaves Poor Hygiene only when it is not Silent, its score is at least the Clear Threshold (70), and its window holds at least 5 Health Reports. A Station hovering at 58, 61, 59, 62 stays flagged. One good Health Report after a silence ends Silent, but it does not clear the flag.
- The **Flag Reason** is `silent`, or whichever of Availability (`availability`), latency score (`latency`) and error score (`errors`) is lowest. Ties go to the first in that order. It is recomputed every run, so it can change while the Station stays flagged.
- Every entry and exit is appended to the Flag Change log (`flag_changes`) with the Station, time, direction (`entered` or `left`), Flag Reason (on leaving, the one it last had while flagged) and score. A Station records "flagged since" when it enters Poor Hygiene, and clears it when it leaves.

A run writes a Station's health row only when its score, Silent, Poor Hygiene, Flag Reason or firmware version changed. The other parts shown (Availability, latency and error scores, p95 latency, report count) are as of that write.

All limits, weights, thresholds and the minimum Health Reports to clear are configurable (see `.env.example`). Each run also records when it ran, how many Stations it scored and how long it took. The worker logs how many rows it wrote and how many Flag Changes it made.

```sh
curl localhost:8000/stations/ST-0001/health -H 'X-API-Key: dev-read-key'
```

This returns the Station's Region, whether it is verified, its latest Health Report (newest `timestamp`, so a late-arriving older Health Report never replaces it), its `hygiene` block (score, Availability, latency score, error score, p95 latency, Health Reports in the window, `silent`, `poor_hygiene`, `flag_reason` and `flagged_since`), and `scored_at`, which is when the last scoring run completed. `hygiene` is `null` until a scoring run has scored the Station. An unknown Station returns `404`.

```sh
curl 'localhost:8000/poor-hygiene?region=eu-west&limit=20' -H 'X-API-Key: dev-read-key'
```

This lists every Station with Poor Hygiene: its Region, whether it is verified, score, `silent`, `flag_reason` and `flagged_since`. Along with `items` it returns `total` (all Stations matching the filters, across every page), `next_cursor` and `scored_at`.

- **Order**: worst score first, with a Silent Station counted as 0. Ties go to the oldest `flagged_since`, then to `station_id`. With `sort=flagged_since` (oldest first) or `sort=-flagged_since` (newest first), ties go to the worst score.
- **Filters**: `region`, `flag_reason` (`silent`, `availability`, `latency`, `errors`) and `verified` (`true` or `false`). They can be combined.
- **Paging**: `limit` sets the page size, 50 by default and at most 500. To get the next page, pass the response's `next_cursor` as `cursor`, keeping the same filters and sort. `next_cursor` is `null` on the last page. The cursor is opaque. It holds the sort key of the last Station on the page, and the next page starts strictly after it. So for a fixed set of Stations, no Station is skipped or repeated. While scores change between requests, a Station whose score moved past the cursor can appear twice or not at all, but the others keep their places. A cursor that is malformed, or that came from another sort, gets `400`.

```sh
curl 'localhost:8000/metrics?group_by=region' -H 'X-API-Key: dev-read-key'
```

This is a snapshot of current health across every registered Station. `overall` holds the station count, Poor Hygiene count and percentage, Silent count, Unverified Station count, and the average Hygiene Score, Availability and p95 latency. It also returns `scored_at`.

- **Grouping**: `group_by=region` or `group_by=firmware_version` adds `groups`, one per key, sorted by key. Stations without a Region go in `unassigned`. Stations no Health Report has given a firmware version for yet go in `unreported`. Both of those come last. Without `group_by`, `groups` is `null`.
- **Firmware version**: each scoring run takes it from the Station's newest Health Report in the Scoring Window. A Silent Station keeps the last one seen.
- **Source**: figures come from Station health and the Station Registry, never from raw Health Reports, so they are as of the last scoring run. A Station registered since that run counts toward the station count only. Averages cover only Stations that have a score, so Silent Stations are left out. Each average is `null` when no Station has a score, and the percentage is `null` when there are no Stations.

```sh
curl 'localhost:8000/metrics/trend?hours=24&group_by=region' -H 'X-API-Key: dev-read-key'
```

This returns one point per completed hour over the past `hours` (24 by default, at most the summary retention in hours), oldest first. The hour in progress is not included. Each point holds the number of Stations that reported in the hour, how many of them had an average Hygiene Score below the Flag Threshold, and their average Hygiene Score, Availability and p95 latency.

- **Source**: points come from hourly summaries, never raw Health Reports. Summaries exist only for Stations that reported, and Silent and Poor Hygiene history is not kept, so a point covers reporting Stations and counts those below the Flag Threshold instead of those with Poor Hygiene. An hour with no summaries is a point with zero counts and `null` averages.
- **Grouping**: `group_by=region` adds `groups`, each with a point for every hour. The Region is the Station's current one. A Station without a Region, or no longer registered, goes in `unassigned`, which comes last.

### Dashboard

http://localhost:8000/dashboard (or `/`, which redirects there) is one page for operators, served by the API. It shows:

- **Summary tiles** from the metrics snapshot: Stations, Poor Hygiene (count and share), Silent, Unverified Stations, and the average Hygiene Score, Availability and p95 latency, with how long ago the last scoring run was.
- **The last 24 hours** from the trend endpoint: the average Hygiene Score per hour and the Stations below the Flag Threshold per hour. An hour with no summaries is a gap.
- **The Poor Hygiene list**, worst first, with each Station's Region, score (or Silent), Flag Reason and how long it has been flagged. It shows the worst 50, with the total.

It refreshes every 30 seconds. It is plain HTML, CSS and JavaScript with no build step and no libraries (`src/station_health/dashboard/`), and it calls only the `read` endpoints `/metrics`, `/metrics/trend` and `/poor-hygiene`.

- **Key**: the page loads without a key, but its data needs a `read` key. docker-compose sets `DASHBOARD_DEMO_KEY=dev-read-key`, which the page carries so it works with no setup, served with `Cache-Control: no-store`. That makes the key readable by anyone who can open the page, so it is for local use only. The service refuses to start if `DASHBOARD_DEMO_KEY` is not a configured key or has any role besides `read`. Without it, the page asks for a read key and keeps it for the browser tab's session.
- Try it with data: `make seed`, `make backfill`, then `make simulate`. The trend fills after the worker's next cycle.

### Station Registry

The Station Registry lists the Stations expected to exist, each with its Region. Managing it needs an `admin` key. `read` and `ingest` keys get `403`.

```sh
make seed N=1000   # register ST-000001..ST-001000, verified, across 5 Regions
curl -X PUT localhost:8000/stations/ST-0042 -H 'X-API-Key: dev-admin-key' \
  -H 'Content-Type: application/json' -d '{"region": "eu-west"}'
curl 'localhost:8000/stations?verified=false' -H 'X-API-Key: dev-admin-key'
curl -X DELETE localhost:8000/stations/ST-0042 -H 'X-API-Key: dev-admin-key'
```

- `PUT /stations/{station_id}` with `{"region": "..."}` (or `null`) registers or updates a Station and marks it verified. It returns `201` when the Station is new, otherwise `200`. Repeating it leaves the Station as it was, apart from its updated time. Registering an Unverified Station confirms it.
- A registered Station that never reports is Silent, so it has Poor Hygiene after the next scoring run.
- `DELETE /stations/{station_id}` returns `204`, or `404` if the Station isn't registered. It removes the Station and its current health, so the Station is no longer scored or listed. Its Health Reports and Flag Changes stay, and the Health Reports age out. A later Health Report for that Station registers it again as an Unverified Station. That Station starts with no flag state, and its Health Reports still in the window count. One exception: a scoring run already under way when the delete lands can write the Station's health row back. The row stays hidden, but a Station registered again later would start from it.
- `GET /stations` lists Stations by `station_id`. `verified=false` shows only Unverified Stations. It is paged like the Poor Hygiene list (`limit` 50 by default, at most 500; pass `next_cursor` as `cursor`).
- `make seed` runs `flask seed-stations --count N` in the API container. It is idempotent: running it again updates the same Stations, and confirms any of them that had reported as Unverified Stations.

### Hourly summaries and retention

After each scoring run the worker writes hourly summaries, then deletes expired rows.

- **Summaries**: one row per Station and completed hour `[hh:00, hh+1:00)` in which it reported. A row holds the report count, online count, average, maximum and p95 latency of online Health Reports, the sum of Error Counts and the average Hygiene Score. The average Hygiene Score is the mean score of the consecutive Scoring Windows that tile the hour (four 15-minute windows by default), each scored like a scoring run. A window with no Health Reports is Silent and counts as 0.
- **Catch-up**: each cycle summarises every completed hour within raw retention that has no summary yet. An hour is summarised 5 minutes after it ends, so Health Reports from its last Probes are in first. So after the worker has been down, it fills in every hour it missed, and backfilled history gets summarised. Running it again writes nothing. Once an hour has summaries, Health Reports that arrive late for it are not added. An hour that started longer ago than raw retention is skipped, because retention may already have deleted part of it.
- **Retention**: raw Health Reports older than `RAW_RETENTION_HOURS` (48) are deleted. That is the same cut-off ingest applies. Hourly summaries are deleted once their hour started more than `SUMMARY_RETENTION_DAYS` (30) before the current hour. Deletes run in batches of `RETENTION_BATCH_SIZE` rows (10,000), each committed on its own. In production the tables would be partitioned by day, and whole partitions dropped instead.
- Each step logs its result. A step that fails is logged and does not stop the others.

### Simulator

The simulator plays the Collector for a fleet of Stations. It sends one Health Report per Station per simulated minute through the HTTP API, using an `ingest` key. It is an optional docker-compose profile, so `make up` doesn't start it.

```sh
make simulate                              # 50 Stations at 60x
make simulate SIM_STATIONS=200 SIM_SPEED=120
docker compose logs -f simulator           # one line per simulated minute
docker compose --profile simulator stop simulator
```

Outside Docker: `PYTHONPATH=src uv run python -m station_health.simulator --help`.

- **Speed**: ingest rejects Health Reports from the future, so simulated time can't run ahead of the clock. Instead it starts 30 minutes in the past (`SIM_BACKLOG_MINUTES`) and runs `SIM_SPEED` times faster than real time until it catches up, then keeps pace with the clock. At the default 60x, the Scoring Window is full after about 30 seconds, so the worker's next scoring run (within a minute) shows every profile. The speed must be above 1, or simulated time never catches up. Timestamps fall on whole minutes, so if the simulator restarts, the Health Reports it resends are duplicates, which ingest ignores.
- **Profiles**: assigned in turn, so half the fleet is healthy and a tenth has each other profile. With the default scoring settings:

  | Profile | Behaviour | Outcome |
  |---|---|---|
  | healthy | online, 40–140 ms, an occasional error | not flagged, score about 100 |
  | flapping | Offline every other minute | Poor Hygiene, `availability`, score about 50 |
  | slow | 1100–1500 ms, and an error every other minute | Poor Hygiene, `latency`, score about 50 |
  | error-prone | fast, 3–5 errors per Health Report | Poor Hygiene, `errors`, score 40 |
  | goes Silent | healthy for its first 10 simulated minutes, then nothing | Poor Hygiene, `silent` |
  | unregistered | healthy, never registered | an Unverified Station |

  A Station that is slow and nothing else scores 60, which is not below the Flag Threshold, because latency carries only 40% of the weight. That is why the slow profile also has a trickle of errors.
- **Stations**: before it starts, the simulator registers its Stations with the `admin` key (`SIM_ADMIN_KEY`). It uses the same IDs and Regions as `make seed` (ST-000001, ...), so the two agree. Unregistered Stations are ST-UNREG-0001, and so on.
- A Health Report the API doesn't accept, or that can't reach it, is logged and dropped, as a real Collector's lost Health Report would be. Settings are in the docker-compose section of `.env.example`.

#### Backfill

Live mode only fills the last half hour, so the trend starts empty. Backfill loads the past hours of Health Reports at once:

```sh
make backfill                              # 50 Stations, the last 24 hours
make backfill SIM_STATIONS=500 HOURS=48
```

It runs `flask backfill-reports --stations N --hours H` in the API container. Outside Docker: `PYTHONPATH=src uv run flask --app station_health.app:create_app backfill-reports --help`.

- **How**: it calls ingest's own validation and storage code directly rather than going through HTTP, and inserts in batches of 5,000. It registers the same fleet as the simulator, with the same profiles and readings, one Health Report per Station per whole minute from `HOURS` ago up to now. Unregistered Stations become Unverified Stations, as they do through ingest. Like the live simulator, it registers its fleet's other Stations as verified with the seed's Regions, so it resets any Region an admin changed for them.
- **Limits**: `HOURS` can be at most raw retention (`RAW_RETENTION_HOURS`, 48), because ingest rejects older Health Reports. Running it again stores nothing new: it reports the Health Reports already stored as duplicates and ignores them. It prints how many it stored, ignored and rejected. At exactly 48 hours, the oldest partial hour is never summarised (catch-up only takes hours wholly within raw retention), and retention deletes it on the next worker cycle, so 47 hours or fewer is the useful maximum.
- **Summaries**: backfill writes no summaries. The worker's next cycle catches up every completed hour, so the trend shows data within a minute (an hour is summarised 5 minutes after it ends).
- **Speed**: 500 Stations over 24 hours (648,500 Health Reports) took about 20 seconds against the test suite's MySQL 8.4 container on a laptop.
- Run it with the same `SIM_STATIONS` as `make simulate`, so live mode carries on with the same Stations. Backfill starts every profile at its first backfilled minute, so the goes-Silent Stations go Silent 10 minutes into the backfilled history.

### Authentication

Every endpoint except `/livez`, `/readyz` and the docs needs an API key in the `X-API-Key` header. Keys map to three roles: `ingest` (the Collector), `read` (operators and the dashboard) and `admin` (Station Registry). Requests with no key, or an unknown key, get `401`. A key without the route's role gets `403`. docker-compose ships demo keys (`dev-ingest-key`, `dev-read-key`, `dev-admin-key`). In Swagger UI, click **Authorize** and paste a key.

### Errors

Every error response has the same JSON shape: `{"code": 422, "status": "Unprocessable Entity", "message": "...", "errors": {...}}`. `message` and `errors` appear when relevant. For validation failures, `errors.json` maps each field to its messages.

### Configuration

All configuration comes from environment variables. `.env.example` documents every setting along with its default. To override any of them, copy it to `.env`; docker-compose picks that file up automatically. Without a `.env`, the defaults just work.

### Logs

Logs go to stdout as JSON, one object per line. Each request gets an ID: the caller's `X-Request-ID` header if it sends one, otherwise a generated one. The ID is echoed in the `X-Request-ID` response header and attached to every log line written while the request is handled, including a summary line per request (`method`, `path`, `status`, `duration_ms`).

## Test

```sh
make install   # uv sync --frozen
make test      # uv run pytest
```

Tests run the real Flask app against a real MySQL 8 that Testcontainers starts. Docker must be running. The Makefile sets `TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE=/var/run/docker.sock`, which colima needs. If you run `pytest` directly under colima, export that variable yourself.

## Lint and type-check

```sh
make lint      # ruff check, ruff format --check, mypy (strict)
make format    # apply ruff fixes and formatting
```

## Layout

The code is organised by feature. Each feature slice owns its routes, schemas and storage.

```
src/station_health/
  app.py          # app factory: config, extensions, logging, blueprints
  config.py       # Settings, read from environment variables
  extensions.py   # SQLAlchemy, Flask-Migrate and flask-smorest instances
  log.py          # JSON log formatter and request-ID middleware
  clock.py        # the injectable clock; tests control "now"
  errors.py       # the one JSON error shape
  auth/           # API keys and roles, applied per route
  reports/        # Health Report ingest: schema, validation, idempotent storage
  paging.py       # opaque cursors and page sizes shared by the list endpoints
  stations/       # Station Registry: admin endpoints, storage, the seed command
  scoring.py      # the pure scoring core: window Health Reports + flag state → Hygiene Score, Poor Hygiene
  health/         # Station health status endpoint, Station health, Flag Change and scoring-run records
  metrics/        # metrics snapshot (from Station health) and hourly trend (from summaries)
  summaries/      # hourly summaries: the pure per-Station hour summary and its table
  worker/         # scoring run, summary catch-up, retention ("run once at now") and the loop
  ops/            # liveness and readiness checks
  dashboard/      # the operator page: a template, plain JS and CSS, no build step
  simulator/      # plays the Collector: scenario profiles (pure), live mode over HTTP, backfill
  migrations/     # Alembic migrations (Flask-Migrate)
tests/            # integration tests against Testcontainers MySQL, unit tests of the scoring core
```
