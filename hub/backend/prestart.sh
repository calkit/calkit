#! /usr/bin/env bash

# Let the DB start
python scripts/backend-pre-start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python scripts/create-initial-data.py
