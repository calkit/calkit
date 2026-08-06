#! /usr/bin/env bash

# Let the DB start
python /app/scripts/backend-pre-start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python /app/scripts/create-initial-data.py
