# 01: Walking skeleton

**What to build:** A reviewer can start the Station Health Service and MySQL with one docker-compose command, open Swagger UI, and hit liveness/readiness checks. Developers can run the test suite against a real MySQL 8 started by Testcontainers. Establishes the feature-sliced app layout (see spec "Modules") with a Flask app factory, flask-smorest, SQLAlchemy, Flask-Migrate, environment-based configuration with a documented example file, and structured JSON logging with a request ID.

Spec: `docs/station-health-service/spec.md` (stories 60, 62, 64, 65, 74–76).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] One docker-compose command starts the API and MySQL 8; migrations are applied at startup or via one documented command
- [ ] Liveness check returns OK when the process is up
- [ ] Readiness check fails when the database is unreachable and passes when it is reachable
- [ ] Swagger UI and the generated OpenAPI document are served
- [ ] Logs are JSON and carry a per-request ID
- [ ] All configuration comes from environment variables; an example env file documents every setting
- [ ] Integration test harness boots the app against a Testcontainers MySQL; a test for liveness/readiness passes
- [ ] A test asserts the generated OpenAPI document is valid
- [ ] README covers prerequisites, run, and test instructions
- [ ] ruff and mypy run clean via a documented make target
