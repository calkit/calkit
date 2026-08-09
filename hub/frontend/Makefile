.PHONY: client
client:
	rm -f openapi.json
	curl http://api.localhost/openapi.json -o openapi.json
	node modify-openapi-operationids.js
	npm run generate-client

.PHONY: format
format:
	@echo "🚀 Formatting frontend"
	@npx biome format --write ./src

.PHONY: test
test:
	@echo "🚀 Running frontend tests"
	@$(MAKE) test-unit
	@npx playwright test --reporter=list

.PHONY: test-unit
test-unit:
	@echo "🚀 Running frontend unit tests"
	@npm run test:unit
