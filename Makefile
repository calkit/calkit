.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.PHONY: install
install: ## Create the project's virtual environment.
	@echo "🚀 Creating virtual environment"
	# --all-packages, since a bare `uv sync` would install only this
	# package and uninstall the hub backend's dependencies from the
	# workspace's single shared .venv
	@uv sync --all-packages

.PHONY: dev
dev: ## Start up the hub containers for development.
	@$(MAKE) -C hub dev

.PHONY: frontend-client
frontend-client: ## Regenerate the hub frontend's API client.
	@$(MAKE) -C hub/frontend client

.PHONY: format
format: sync-docs sync-resources ## Automatically format files.
	@echo "🚀 Linting code with pre-commit"
	@uv run pre-commit run -a

.PHONY: check
check: format ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Static type checking with mypy"
	@uv run --all-packages mypy
	@echo "🚀 Checking for obsolete dependencies with deptry"
	@uv run deptry .

.PHONY: test
test: ## Test the code with pytest.
	@echo "🚀 Testing code with pytest"
	@uv run pytest

.PHONY: test-cov
test-cov: ## Test the code coverage with pytest.
	@echo "🚀 Testing code coverage with pytest"
	@uv run pytest --cov --cov-config=pyproject.toml

.PHONY: test-docs
test-docs: sync-docs ## Test if documentation can be built without warnings or errors.
	@uv run mkdocs build -s

.PHONY: schema
schema: ## Generate the published JSON schema for calkit.yaml.
	@echo "🚀 Generating calkit.yaml JSON schema"
	@uv run calkit describe schema -o docs/schemas/calkit.json
	@uv run calkit describe schema --for provenance \
		-o docs/schemas/provenance.json
	@cp docs/schemas/calkit.json vscode-ext/schemas/calkit.json

.PHONY: sync-docs
sync-docs: schema ## Sync documentation content from docs/*.md into README.md.
	@echo "🚀 Generating docs references"
	@uv run python scripts/generate-docs-references.py
	@echo "🚀 Syncing documentation"
	@uv run python scripts/sync-docs.py

.PHONY: unreleased
unreleased: ## List each product's commits since its last release.
	@uv run python scripts/list-changes.py

.PHONY: sync-resources
sync-resources: ## Regenerate the dev container spec from the VS Code config.
	@echo "🚀 Syncing project resources"
	@uv run python scripts/sync-resources.py

.PHONY: devcontainer-image
devcontainer-image: ## Build the dev container image and smoke test it.
	@echo "🚀 Building the dev container image"
	@docker build -t calkit/devcontainer:dev calkit/resources/devcontainer
	@echo "🚀 Smoke testing the dev container image"
	@docker run --rm calkit/devcontainer:dev bash -c \
		"calkit --version && uv --version && pixi --version && conda --version"

.PHONY: docs
docs: sync-docs ## Build and serve the documentation.
	@uv run mkdocs serve --livereload

.PHONY: import-profile
import-profile: ## Profile the import time of the CLI.
	uv run python -X importtime -m calkit --help 2> import.log && uvx tuna import.log

.PHONY: jlab-dev
jlab-dev: ## Develop the JupyterLab extension.
	cd jupyterlab-ext && uv run jlpm run watch

.PHONY: jlab
jlab: ## Build the JupyterLab extension.
	cd jupyterlab-ext && uv run jlpm run build:prod

.PHONY: test-jlab
test-jlab: ## Run JupyterLab extension unit tests with Jest.
	@echo "🚀 Running JupyterLab extension unit tests"
	@cd jupyterlab-ext && uv run jlpm test

.PHONY: test-jlab-ui
test-jlab-ui: ## Run the JupyterLab UI integration tests.
	@echo "🚀 Running JupyterLab UI tests with Playwright"
	@cd jupyterlab-ext && uv run jlpm run build:prod
	@uv run --directory=jupyterlab-ext/ui-tests jlpm install
	@uv run --directory=jupyterlab-ext/ui-tests jlpm playwright install
	@uv run --directory=jupyterlab-ext/ui-tests jlpm playwright test -u --reporter=list

.PHONY: browser-ext
browser-ext: ## Build the browser extension and package it as a ZIP.
	@echo "🚀 Building the browser extension"
	@cd browser-ext && npm ci && npm run build
	@echo "📦 Packaging the browser extension ZIP"
	@mkdir -p browser-ext/zip
# Packaged from a staged copy, never from dist: dist is what gets loaded
# unpacked for development, and the published manifest drops the local
# hub's host permission, which development needs.
	@rm -rf browser-ext/zip/stage
	@mkdir -p browser-ext/zip/stage
	@cp -R browser-ext/dist/. browser-ext/zip/stage/
	@cd browser-ext && node scripts/package-manifest.mjs zip/stage/manifest.json
# Source maps are useful loading unpacked, but only bloat a store upload, so
# they stay in dist and are excluded from the archive.
# zip adds to an existing archive rather than replacing it, so a rebuild at
# the same commit would otherwise keep files the build no longer produces.
# $$ escapes the shell's expansion from Make's own.
	@rm -f "browser-ext/zip/calkit-browser-ext.zip"
	@cd browser-ext/zip/stage && zip -qr \
		"../calkit-browser-ext.zip" . \
		-x '.*' '*/.*' '*.map'
	@rm -rf browser-ext/zip/stage

.PHONY: browser-ext-dev
browser-ext-dev: ## Rebuild the browser extension on every change.
	@echo "🚀 Watching the browser extension"
# Rebuilds on save. Chrome still needs the extension reloaded, since it
# reads a content script from disk when a page loads. Vite doesn't type
# check, so run 'cd browser-ext && npm run check' alongside this.
	@cd browser-ext && npm ci && npm run dev

.PHONY: browser-ext-clean-zips
browser-ext-clean-zips: ## Delete all built browser extension ZIPs.
	@rm -rf browser-ext/zip
