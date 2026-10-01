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

This builds the image, starts MySQL 8, the API and the worker, and applies database migrations (`flask db upgrade`) before the API starts serving. The worker is the same image running `python -m station_health.worker`: every 60 seconds (`WORKER_INTERVAL_SECONDS`) it performs a scoring run. Once it is up:

| URL | What |
|---|---|
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/openapi.json | Generated OpenAPI document |
| http://localhost:8000/livez | Liveness: `200` while the process is up |
| http://localhost:8000/readyz | Readiness: `200` when the database is reachable, `503` when it is not |

Other targets: `make logs` (follow API and worker logs), `make migrate` (re-apply migrations in the running container), `make down` (stop; `docker compose down -v` also drops the database volume).

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

The worker scores every Station that has Health Reports in the Scoring Window, the last 15 minutes (`SCORING_WINDOW_MINUTES`), in one grouped read:

- **Availability**: the share of Health Reports in the window that are not Offline.
- **Latency score**: from the p95 latency of online Health Reports only. It is 1.0 at or below 150 ms, 0.0 at or above 1000 ms, and linear in between. The p95 uses nearest rank, so it is always an observed latency. With 15 Health Reports per window, that is the slowest one.
- **Error score**: from errors per online Health Report (Error Count summed over online Health Reports only). It is 1.0 at 0 and 0.0 at 3 or more.
- **Hygiene Score** = Availability × (0.4 × latency score + 0.6 × error score) × 100, rounded half up. A Station with no online Health Reports in the window scores 0, and its latency and error scores are `null` because nothing was measured.

All limits and weights are configurable (see `.env.example`). Each run also records when it ran, how many Stations it scored and how long it took.

```sh
curl localhost:8000/stations/ST-0001/health -H 'X-API-Key: dev-read-key'
```

This returns the Station's Region, whether it is verified, its latest Health Report (newest `timestamp`, so a late-arriving older Health Report never replaces it), its `hygiene` block (score, Availability, latency score, error score, p95 latency, and Health Reports in the window), and `scored_at`, which is when the last scoring run completed. `hygiene` is `null` until a scoring run has scored the Station. An unknown Station returns `404`.

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
  stations/       # Station Registry
  scoring.py      # the pure scoring core: window Health Reports → Hygiene Score
  health/         # Station health status endpoint, Station health and scoring-run records
  worker/         # the scoring run ("run once at now") and the worker loop process
  ops/            # liveness and readiness checks
  migrations/     # Alembic migrations (Flask-Migrate)
tests/            # integration tests against Testcontainers MySQL, unit tests of the scoring core
```
