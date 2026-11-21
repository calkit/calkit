.PHONY: test
test:
	@$(MAKE) -s -C .. dotenv
	docker compose exec backend bash ./tests-start.sh

.PHONY: format
format:
	@echo "🚀 Formatting backend"
	@uv run ruff format
