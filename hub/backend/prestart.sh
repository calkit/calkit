#! /usr/bin/env bash

# Exit in case of error. Without this, a failed `alembic upgrade` is swallowed,
# this script still exits 0, and the backend starts against a database whose
# schema doesn't match the models, turning a loud migration error into runtime
# 500s on every query touching a missing column
set -e

# Let the DB start
python scripts/backend-pre-start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python scripts/create-initial-data.py
