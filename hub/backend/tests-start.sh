#! /usr/bin/env bash
set -e
set -x

# Run tests against an isolated DB so local dev data is never mutated
TEST_POSTGRES_DB="${POSTGRES_DB_TEST:-${POSTGRES_DB}_test}"
export POSTGRES_DB="$TEST_POSTGRES_DB"

python - <<'PY'
import os

import psycopg
from psycopg import sql

host = os.environ["POSTGRES_SERVER"]
port = int(os.environ.get("POSTGRES_PORT", "5432"))
user = os.environ["POSTGRES_USER"]
password = os.environ.get("POSTGRES_PASSWORD", "")
test_db = os.environ["POSTGRES_DB"]

with psycopg.connect(
	host=host,
	port=port,
	user=user,
	password=password,
	dbname="postgres",
	autocommit=True,
) as conn:
	with conn.cursor() as cur:
		cur.execute(
			"""
			SELECT pg_terminate_backend(pid)
			FROM pg_stat_activity
			WHERE datname = %s
			  AND pid <> pg_backend_pid()
			""",
			(test_db,),
		)
		cur.execute(
			sql.SQL("DROP DATABASE IF EXISTS {}")
			.format(sql.Identifier(test_db))
		)
		cur.execute(
			sql.SQL("CREATE DATABASE {} TEMPLATE template0")
			.format(sql.Identifier(test_db))
		)
PY

python /app/scripts/backend-pre-start.py
alembic upgrade head
python /app/scripts/create-initial-data.py

bash ./scripts/test.sh "$@"
