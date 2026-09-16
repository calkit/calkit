FROM python:3.14

# The build context is the repo root, not this directory, so the image can
# install the calkit-python workspace member from the working tree

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

# calkit-python's build hooks build the JupyterLab extension, which needs
# Node and is not used by the backend
ENV HATCH_BUILD_NO_HOOKS=true

# Install dependencies
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=hub/backend/pyproject.toml,target=hub/backend/pyproject.toml \
    uv sync --package app --frozen --no-install-workspace

ENV PYTHONPATH=/app/hub/backend

ENV PYTHONUNBUFFERED=1

COPY ./pyproject.toml ./uv.lock ./README.md /app/

COPY ./calkit /app/calkit

COPY ./agent-plugin /app/agent-plugin

COPY ./hub/backend /app/hub/backend

# Sync the project
#
# .git is bind-mounted, not copied: hatch-vcs reads the release tags through
# it to version both workspace members, and a mount leaves nothing behind in
# the image. This layer already re-runs whenever the sources above change,
# so making it depend on the repository costs no cache that wasn't already
# being spent.
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=.git,target=/app/.git,ro \
    uv sync --package app --frozen

# Fail the build if PyYAML wasn't linked against libyaml. The C loader is
# ~10x faster for large dvc.lock parses and we rely on it in the hot path.
RUN python -c "import yaml; assert yaml.__with_libyaml__, 'PyYAML built without libyaml'"

WORKDIR /app/hub/backend

CMD ["fastapi", "run", "--workers", "4", "app/main.py"]
