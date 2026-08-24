# Installs only when the lockfile is newer than what's installed, so a
# missing or stale node_modules can't fail a target halfway through --
# which is what 'openapi-ts: command not found' was.
node_modules: package-lock.json
	npm ci
	@touch node_modules

.PHONY: client
client: node_modules
	rm -f openapi.json
	curl http://api.localhost/openapi.json -o openapi.json
	node modify-openapi-operationids.js
	npm run generate-client

.PHONY: format
format: node_modules
	@echo "🚀 Formatting frontend"
	@npx biome format --write ./src

.PHONY: test
test: node_modules
	@echo "🚀 Running frontend tests"
	@$(MAKE) test-unit
	@npx playwright test --reporter=list

.PHONY: test-unit
test-unit: node_modules
	@echo "🚀 Running frontend unit tests"
	@npm run test:unit
