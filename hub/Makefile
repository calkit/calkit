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

# Each worktree's stack is its own Compose project, so branches don't share a
# database or DVC data. Compose reads the name from COMPOSE_PROJECT_NAME in
# .env, so plain docker compose commands reach this worktree's stack too.
# It's named for the worktree's directory, so the checkout named calkit keeps
# the original calkit stack.
STACK_NAME=$(shell basename "$(abspath ..)" | tr A-Z a-z | \
	tr -c 'a-z0-9_\n-' - | sed '/^calkit/!s/^/calkit-/')
# A new worktree has no .env, since it's gitignored, so it starts from the
# main checkout's, minus its stack name
MAIN_ENV=$(shell dirname "$$(git rev-parse --path-format=absolute \
	--git-common-dir)")/hub/.env

.PHONY: dotenv
dotenv: ## Create .env if needed and name this worktree's stack in it.
	@if [ ! -f .env ]; then \
		test -f "$(MAIN_ENV)" || \
			{ echo "No .env; create one from the template"; exit 1; }; \
		echo "Copying $(MAIN_ENV)"; \
		grep -v '^COMPOSE_PROJECT_NAME=' "$(MAIN_ENV)" > .env || true; \
	fi
	@grep -q '^COMPOSE_PROJECT_NAME=' .env || \
		printf '\n# Dev stack for this worktree\nCOMPOSE_PROJECT_NAME=%s\n' \
		"$(STACK_NAME)" >> .env

# Stacks share ports, so another worktree's would make up fail partway
.PHONY: ports-free
ports-free:
	@others=$$(docker ps --format '{{.Label "com.docker.compose.project"}} {{.Label "com.docker.compose.project.working_dir"}}' \
		| awk -v d="$(CURDIR)" '$$2 ~ /\/hub$$/ && $$2 != d' | sort -u); \
	if [ -n "$$others" ]; then \
		echo "Another hub stack is running; stop it first:"; \
		echo "$$others" | while read -r p d; do \
			echo "    docker compose -p $$p stop    # from $$d"; \
		done; \
		exit 1; \
	fi

.PHONY: tex-engine
tex-engine: ## Download the TeX Live bundles for the LaTeX editor (idempotent).
	@bash frontend/scripts/download-tex-engine.sh

# A `up` that fails partway (a port already bound, most often) can leave
# containers running but attached to no network, which every log reports as
# a healthy start and every client as a dead service.
.PHONY: fix-unattached
fix-unattached: dotenv ## Recreate containers left with no network by a failed up.
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
dev: tex-engine dotenv ports-free fix-unattached ## Start up all containers for development.
	${DOCKER_COMPOSE_DEV} up

.PHONY: api-dev
api-dev: dotenv ports-free ## Start the backend alone using Docker Compose.
	${DOCKER_COMPOSE_DEV} up backend

.PHONY: local-api
local-api: ## Run the FastAPI backend directly.
	cd backend && make local-api

.PHONY: build-dev
build-dev: dotenv ## Build containers for development.
	${DOCKER_COMPOSE_DEV} build

# The regular (non-superuser) account to wipe, so the next sign-in with it
# sees what a new user sees
DEV_USER_EMAIL ?= $(shell grep -E '^DEV_USER_EMAIL=' .env 2>/dev/null | cut -d= -f2-)

.PHONY: dev-reset-user
dev-reset-user: dotenv ## Delete the dev user and their projects (DEV_USER_EMAIL in .env, or EMAIL=...).
	@test -n "$(or $(EMAIL),$(DEV_USER_EMAIL))" || (echo "Set DEV_USER_EMAIL in .env or pass EMAIL=you@example.com"; exit 1)
	${DOCKER_COMPOSE_DEV} run --rm --no-deps -T backend python scripts/delete-user.py $(or $(EMAIL),$(DEV_USER_EMAIL))

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
