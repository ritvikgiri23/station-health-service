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

This builds the image, starts MySQL 8 and the API, and applies database migrations (`flask db upgrade`) before the API starts serving. Once it is up:

| URL | What |
|---|---|
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/openapi.json | Generated OpenAPI document |
| http://localhost:8000/livez | Liveness: `200` while the process is up |
| http://localhost:8000/readyz | Readiness: `200` when the database is reachable, `503` when it is not |

Other targets: `make logs` (follow API logs), `make migrate` (re-apply migrations in the running container), `make down` (stop; `docker compose down -v` also drops the database volume).

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
  ops/            # liveness and readiness checks
  migrations/     # Alembic migrations (Flask-Migrate)
tests/            # integration tests against Testcontainers MySQL
```
