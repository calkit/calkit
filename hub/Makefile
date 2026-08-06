.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

DOCKER_COMPOSE_DEV=docker compose -f docker-compose.yml -f docker-compose.override.yml

.PHONY: tex-engine
tex-engine: ## Download the TeX Live bundles for the LaTeX editor (idempotent).
	@bash frontend/scripts/download-tex-engine.sh

.PHONY: dev
dev: tex-engine ## Start up all containers for development.
	${DOCKER_COMPOSE_DEV} up

.PHONY: frontend-dev
frontend-dev: tex-engine ## Start the frontend dev server.
	cd frontend && npm run dev

.PHONY: api-dev
api-dev: ## Start the backend alone using Docker Compose.
	${DOCKER_COMPOSE_DEV} up backend

.PHONY: local-api
local-api: ## Run the FastAPI backend directly.
	cd backend && make local-api

.PHONY: build-dev
build-dev: ## Build containers for development.
	${DOCKER_COMPOSE_DEV} build

.PHONY: format
format: ## Format all code (runs every pre-commit hook over all files).
	@uvx prek run --all-files

.PHONY: frontend-client
frontend-client: ## Regenerate the OpenAPI client for the frontend.
	@cd frontend && make client

.PHONY: frontend
frontend: ## Build the frontend.
	@cd frontend && npm run build

.PHONY: test-frontend
test-frontend: ## Run frontend unit tests then end-to-end tests.
	@cd frontend && make test

.PHONY: test-backend
test-backend: ## Run backend tests.
	@cd backend && make test
