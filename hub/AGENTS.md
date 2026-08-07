# Agent guidelines for the Calkit hub

This document provides guidance for agents working on this repository.

## Regenerating the OpenAPI Client

When the backend API changes, regenerate the frontend OpenAPI client:

```bash
make frontend-client
```

This runs `npm run generate-client` in the frontend directory, which:
- Reads `openapi.json` (generated from FastAPI)
- Generates TypeScript client SDK files in `frontend/src/client`
- Formats the output with Biome

## Code Formatting

Format all code (frontend and backend) in one command:

```bash
make format
```

This applies the formatters configured for each service.

## Database Migrations

Database migrations are handled with Alembic. **Before creating or modifying migrations, read [docs/dev/database-migrations.md](docs/dev/database-migrations.md).**

Key points:
- Define new tables as `SQLModel` classes in `backend/app/models/core.py`
- Generate migrations with: `docker compose exec backend alembic revision --autogenerate -m "Description"`
- Apply migrations with: `docker compose exec backend alembic upgrade head`
- Check current version with: `alembic current` (from `backend/` directory)
- Squash into one per branch/PR

## Development Environment

- **Backend**: FastAPI in `backend/` directory
- **Frontend**: React + Vite in `frontend/` directory
- **Docker**: Services orchestrated with Docker Compose; see `docker-compose.yml`
- **Development**: Use `make dev` to start all services

## Testing

- Run frontend tests: `make test-frontend`
- Run backend tests: `make test-backend`

These use an isolated test database inside containers. Don't try to run tests
out on the system.

## Troubleshooting

### A frontend request "500s" but the backend looks fine

In dev (`make dev`), the frontend is the Vite dev server with `frontend/` mounted
in, and `frontend/src/client` (the OpenAPI SDK) plus `routeTree.gen.ts` are
generated files. After changing a backend route or running
`make frontend-client`, a stale dev server or a cached browser bundle can call
the old contract and surface as a confusing error that looks like a 500 but
isn't coming from the backend.

Before assuming a real server bug, confirm where it comes from:

1. Check the browser Network tab for the actual status code, and read the
   backend logs (`docker compose logs -f backend`). A real 500 shows a Python
   traceback there; a stale frontend does not.
2. If the backend log is clean, refresh the stale frontend:
   - Regenerate the client if the API changed: `make frontend-client`.
   - Restart the dev server: `docker compose restart frontend`.
   - Hard-refresh the browser (clear cache) to drop the old bundle.

If instead you are running the built image (plain `docker compose up`, not
`make dev`), the frontend is a static Nginx build and will keep serving old code
until you rebuild it: `docker compose build frontend`.

## Common Patterns

### Modifying API Contracts

1. Update backend route in `backend/app/api/routes/`
2. Regenerate the client: `make frontend-client`
3. Update frontend code to use new/changed SDK methods
4. Format both: `make format`

### Adding Database Features

1. Add `SQLModel` class in `backend/app/models/core.py`
2. Create migration: `docker compose exec backend alembic revision --autogenerate -m "Add new_table"`
3. Apply migration: `docker compose exec backend alembic upgrade head`
4. Commit the migration file in `backend/app/alembic/versions/`

### Building and Testing

- Local frontend build: `cd frontend && npm run build`
- Docker frontend build: `docker compose build frontend`
- Backend tests: `make test-backend`

## Misc rules

- Git commits and pushes are for humans, not agents.
- No blank lines in functions.
- API endpoint functions should start with their REST verbs,
  e.g., `post_something` or `get_something`.
- Search inputs should always be clearable.
- Disable browser and password manager autocomplete on most form fields,
  e.g., with `autoComplete="off"`, `data-form-type="other"`, and
  `data-lpignore="true"`, since they usually don't hold personal information.
  Leave it on for genuine personal fields, e.g., login email and password.
- Changes to the UI state, e.g., a selected tab or a modal open,
  should typically be part of query params so a link will show a similar state.
- Tooltips should always have the same hover delay site-wide.
- Always put a comma after "i.e." and "e.g.".
- Let humans write prose.
- Don't use em dashes in user-facing copy (labels, helper text, toasts, emails).
  They read as AI-written. Use a comma, period, or rewrite. Prose is for humans.
- Modal open state should be a query param.
- Most front end state, e.g., an expanded section of a list,
  should also be a query param, so the back button works properly.
- Function names should typically always start with a verb.
- Avoid extracting helper functions unless they are used in 3 or more places
  or significantly help testing.
- Don't use comment separators like `# ---- Section ----` to divide up modules.
  Group related code with real structure (functions, classes) instead.
