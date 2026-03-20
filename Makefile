.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.PHONY: install
install: ## Create the project's virtual environment.
	@echo "🚀 Creating virtual environment"
	@uv sync

.PHONY: format
format: sync-docs ## Automatically format files.
	@echo "🚀 Linting code with pre-commit"
	@uv run pre-commit run -a

.PHONY: check
check: format ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Static type checking with mypy"
	@uv run mypy .
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

.PHONY: sync-docs
sync-docs: cli-reference ## Sync documentation content from docs/*.md into README.md.
	@echo "🚀 Syncing documentation"
	@uv run python scripts/sync-docs.py

.PHONY: cli-reference
cli-reference: ## Generate docs/cli-reference.md from CLI help output.
	@echo "🚀 Generating CLI reference"
	@uv run python scripts/generate-cli-reference.py

.PHONY: docs
docs: sync-docs ## Build and serve the documentation.
	@uv run mkdocs serve --livereload

.PHONY: import-profile
import-profile: ## Profile the import time of the CLI.
	uv run python -X importtime -m calkit --help 2> import.log && uvx tuna import.log

.PHONY: jlab-dev
jlab-dev: ## Develop the JupyterLab extension.
	uv run jlpm run watch

.PHONY: jlab
jlab: ## Build the JupyterLab extension.
	uv run jlpm run build:prod

.PHONY: test-frontend
test-frontend: ## Run frontend unit tests with Jest.
	@echo "🚀 Running frontend unit tests"
	@uv run jlpm test

.PHONY: test-ui
test-ui: ## Run the JupyterLab UI integration tests.
	@echo "🚀 Running JupyterLab UI tests with Playwright"
	@uv run npm run build
	@uv run --directory=ui-tests jlpm playwright test -u --reporter=list
