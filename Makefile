.DEFAULT_GOAL := help

# Testcontainers mounts the Docker socket into its reaper container. This is the
# in-VM socket path for Docker Desktop, colima and OrbStack alike.
export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE ?= /var/run/docker.sock

.PHONY: help install up down logs migrate seed simulate backfill test lint format

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install pinned dependencies into .venv
	uv sync --frozen

up: ## Build and start the API, worker and MySQL (migrations run on startup)
	docker compose up --build -d

down: ## Stop containers (add -v to the command to also drop the database)
	docker compose down

logs: ## Follow API and worker logs
	docker compose logs -f api worker

migrate: ## Apply migrations in the running API container
	docker compose exec api flask --app station_health.app:create_app db upgrade

seed: ## Load N Stations (default 1000) across 5 Regions into the running stack: make seed N=5000
	docker compose exec api flask --app station_health.app:create_app seed-stations --count $(or $(N),1000)

simulate: ## Start the simulator (optional compose profile): make simulate SIM_STATIONS=100 SIM_SPEED=60
	docker compose --profile simulator up --build -d simulator

backfill: ## Load past Health Reports for the simulator's fleet: make backfill SIM_STATIONS=500 HOURS=24
	docker compose exec api flask --app station_health.app:create_app backfill-reports --stations $(or $(SIM_STATIONS),50) --hours $(or $(HOURS),24)

test: ## Run the test suite (needs Docker for Testcontainers)
	uv run pytest

lint: ## ruff check, ruff format --check and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format: ## Auto-fix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .
