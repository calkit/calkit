FROM python:3.14

WORKDIR /app/

# Install uv (pinned by version and digest for reproducible builds)
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.11.2@sha256:c4f5de312ee66d46810635ffc5df34a1973ba753e7241ce3a08ef979ddd7bea5 /uv /uvx /bin/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# Use the base image interpreter instead of downloading managed Python builds
ENV UV_PYTHON_DOWNLOADS=never

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project

ENV PYTHONPATH=/app

ENV PYTHONUNBUFFERED=1

COPY ./scripts /app/scripts

COPY ./alembic.ini /app/

COPY ./prestart.sh /app/

COPY ./tests-start.sh /app/

COPY ./pyproject.toml ./uv.lock /app/

COPY ./app /app/app

# Sync the project
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen

# Fail the build if PyYAML wasn't linked against libyaml. The C loader is
# ~10x faster for large dvc.lock parses and we rely on it in the hot path.
RUN python -c "import yaml; assert yaml.__with_libyaml__, 'PyYAML built without libyaml'"

CMD ["fastapi", "run", "--workers", "4", "app/main.py"]
