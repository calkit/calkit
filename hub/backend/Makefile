.PHONY: test
test:
	docker compose exec backend bash ./tests-start.sh

.PHONY: format
format:
	@echo "🚀 Formatting backend"
	@uv run ruff format
