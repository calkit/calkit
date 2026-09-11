.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

# --profile objects runs the bundled MinIO; profiles can only be
# activated from the command line or COMPOSE_PROFILES, never from a
# compose file, and keeping it out of .env keeps it out of containers
DOCKER_COMPOSE_DEV=docker compose --profile objects -f docker-compose.yml -f docker-compose.override.yml

# The backend reports this at /version. The image can't derive it: .git is
# excluded from its build context, so it's resolved here, where the
# repository is. Matched on the hub/v prefix because this monorepo also
# tags the Python package as vX.Y.Z.
export HUB_VERSION ?= $(shell git describe --tags --match 'hub/v*' --always 2>/dev/null)

.PHONY: tex-engine
tex-engine: ## Download the TeX Live bundles for the LaTeX editor (idempotent).
	@bash frontend/scripts/download-tex-engine.sh

# A `up` that fails partway (a port already bound, most often) can leave
# containers running but attached to no network, which every log reports as
# a healthy start and every client as a dead service.
.PHONY: fix-unattached
fix-unattached: ## Recreate containers left with no network by a failed up.
	@broken=""; \
	for s in $$(${DOCKER_COMPOSE_DEV} ps --services --status running); do \
		cid=$$(${DOCKER_COMPOSE_DEV} ps -q $$s); \
		[ -n "$$cid" ] || continue; \
		ip=$$(docker inspect $$cid \
			--format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' \
			| tr -d ' '); \
		[ -n "$$ip" ] || broken="$$broken $$s"; \
	done; \
	if [ -n "$$broken" ]; then \
		echo "Recreating unattached containers:$$broken"; \
		${DOCKER_COMPOSE_DEV} up -d --force-recreate $$broken; \
	fi

.PHONY: dev
dev: tex-engine fix-unattached ## Start up all containers for development.
	${DOCKER_COMPOSE_DEV} up

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
