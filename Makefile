.DEFAULT_GOAL := help

# Testcontainers mounts the Docker socket into its reaper container. This is the
# in-VM socket path for Docker Desktop, colima and OrbStack alike.
export TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE ?= /var/run/docker.sock

.PHONY: help install up down logs migrate test lint format

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "} {printf "  %-10s %s\n", $$1, $$2}'

install: ## Install pinned dependencies into .venv
	uv sync --frozen

up: ## Build and start the API and MySQL (migrations run on startup)
	docker compose up --build -d

down: ## Stop containers (add -v to the command to also drop the database)
	docker compose down

logs: ## Follow API logs
	docker compose logs -f api

migrate: ## Apply migrations in the running API container
	docker compose exec api flask --app station_health.app:create_app db upgrade

test: ## Run the test suite (needs Docker for Testcontainers)
	uv run pytest

lint: ## ruff check, ruff format --check and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format: ## Auto-fix lint issues and format
	uv run ruff check --fix .
	uv run ruff format .
