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

**Never invoke `pytest` directly, even inside the backend container.** The
isolation comes from `backend/tests-start.sh`, which points `POSTGRES_DB` at
a throwaway `*_test` database, recreates it, and migrates it before handing
off to pytest. A bare `docker compose exec backend pytest ...` skips all of
that and runs against the **development database**, where the fixtures
create users and projects that then stay there.

To run a subset, pass pytest's arguments through the same script rather than
reaching for pytest yourself:

```sh
docker compose exec backend bash ./tests-start.sh app/tests/api/routes/test_users.py -k onboarding -q
```

Note the paths are relative to `backend/`, which is the container's working
directory, not the repo root.

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

### A frontend request fails with a network error

A network error (as opposed to an HTTP status) means nothing answered, so the
backend is most likely not running. Check with `docker compose ps -a`: if
`backend` shows `exited (1)`, read `docker compose logs backend` for the
traceback.

An `ImportError` or `ModuleNotFoundError` from `calkit` there — for example
`cannot import name 'MARIMO_DETECT_N_BYTES' from 'calkit.notebooks'` — usually
means the container's virtual environment is stale, not that the code is wrong.
In dev, `docker-compose.override.yml` mounts the repo at `/app` and masks the
image's environment with an **anonymous volume** at `/app/.venv`. That volume
outlives `docker compose build` and `up --force-recreate`, so an environment
created months ago keeps shadowing the working tree no matter how often the
image is rebuilt. Renew it explicitly:

```sh
docker compose build backend
docker compose up -d --renew-anon-volumes backend
```

`--renew-anon-volumes` only discards anonymous volumes; named volumes such as
the database keep their data. Reach for this after merging a branch that changes
dependencies or moves code between calkit-python and the backend.

Once the volume is current, calkit-python is installed as an editable workspace
member resolving to `/app/calkit`, so host edits to it are live and this should
not recur until the environment itself needs to change.

### Postgres errors that a column does not exist

A log full of `ERROR: column project.<something> does not exist` means the
schema is behind the models: migrations did not run. Check why in the prestart
logs, not the backend's:

```sh
docker compose logs prestart
```

`Can't locate revision identified by '<rev>'` means `alembic_version` points at
a revision that isn't in `backend/app/alembic/versions/`, so alembic refuses to
run anything and the schema freezes wherever it was. This comes from having
migrated the dev database while on a branch whose migration was later squashed,
renamed, or abandoned — the revision can be gone from git entirely, so don't
assume it is recoverable (`git log --all -S '<rev>'` to find out).

The reliable fix on a dev database is to recreate it, since all data is seeded
by `create-initial-data.py` anyway:

```sh
docker compose down db
docker volume rm calkit_app-db-data
docker compose up -d db backend
```

Repairing in place is possible but fiddly: the abandoned branch has usually
applied *some* of its DDL, so the database is genuinely half-migrated rather
than merely mis-stamped. It takes `alembic stamp <rev> --purge` (plain `stamp`
also reads the current revision and hits the same error) to a revision known to
predate the divergence, then hand-applying whatever the next migration would
have done that isn't already there, then `alembic upgrade head`.

Either way, verify the result against a from-scratch migration rather than
trusting the stamp — build a scratch database, migrate it from empty, and diff:

```sh
docker compose exec db psql -U postgres -d postgres -c "CREATE DATABASE app_check"
docker compose exec -e POSTGRES_DB=app_check backend alembic upgrade head
docker compose exec db pg_dump -U postgres -d app --schema-only > /tmp/a.sql
docker compose exec db pg_dump -U postgres -d app_check --schema-only > /tmp/b.sql
diff /tmp/a.sql /tmp/b.sql
docker compose exec db psql -U postgres -d postgres -c "DROP DATABASE app_check"
```

Note that `alembic check` is not a clean signal here: it reports drift
(a missing `ck_account_name_lowercase` check constraint, some foreign-key
churn) even against a perfectly migrated database, because the models don't
declare those constraints. The from-scratch diff is what distinguishes real
divergence from that baseline noise.

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
- No blank lines in functions. This only covers blank lines we write, not ones
  the auto-formatter inserts, e.g., ruff-format adds one after an in-function
  import block. Don't delete those; `ruff format` will just put them back.
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
