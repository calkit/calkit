.PHONY: test
test:
	bash ../scripts/dev-stack.sh exec backend bash ./tests-start.sh

.PHONY: format
format:
	@echo "🚀 Formatting backend"
	@uv run ruff format
