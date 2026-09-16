.PHONY: help
help: ## Show this help.
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.PHONY: install
install: ## Create the project's virtual environment.
	@echo "🚀 Creating virtual environment"
	@uv sync

.PHONY: test
test: ## Test the code with pytest.
	@echo "🚀 Testing code with pytest"
	@uv run pytest

.PHONY: test-cov
test-cov: ## Test the code coverage with pytest.
	@echo "🚀 Testing code coverage with pytest"
	@uv run pytest --cov --cov-config=pyproject.toml

.PHONY: gui
gui: ## Run the GUI in dev mode.
	@uv run main.py

.PHONY: build
build: ## Build the GUI with PyInstaller.
	@uv run pyinstaller --onefile --icon resources/icon.ico --name calkit-assistant main.py

.PHONY: icon
icon: ../hub/frontend/public/assets/images/c-to-the-k.svg ## Create the app icon.
	@convert -density 256x256 -background transparent $< -define icon:auto-resize -colors 256 resources/icon.ico
