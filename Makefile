.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.PHONY: install
install: ## Create the project's virtual environment.
	@echo "🚀 Creating virtual environment"
	@uv sync

.PHONY: format
format: ## Automatically format files.
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

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors.
	@uv run mkdocs build -s

.PHONY: docs
docs: ## Build and serve the documentation.
	@uv run mkdocs serve
