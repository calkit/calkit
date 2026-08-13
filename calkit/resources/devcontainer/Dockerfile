FROM mcr.microsoft.com/devcontainers/python:dev-3.13-bullseye

# GHCR links a package to the repo named here, which is what makes the
# package inherit this repo's permissions and show its source
LABEL org.opencontainers.image.source=https://github.com/calkit/calkit

# Install Miniforge
ARG MINIFORGE_NAME=Miniforge3
ARG MINIFORGE_VERSION=26.3.2-0
ARG TARGETPLATFORM

ENV CONDA_DIR=/opt/conda
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8
ENV PATH=${CONDA_DIR}/bin:${PATH}

# 1. Install just enough for conda to work
# 2. Keep $HOME clean (no .wget-hsts file), since HSTS isn't useful in this context
# 3. Install miniforge from GitHub releases
# 4. Apply some cleanup tips from https://jcrist.github.io/conda-docker-tips.html
#    Particularly, we remove pyc and a files. The default install has no js, we can skip that
# 5. Activate base by default when running as any *non-root* user as well
#    Good security practice requires running most workloads as non-root
#    This makes sure any non-root users created also have base activated
#    for their interactive shells.
# 6. Activate base by default when running as root as well
#    The root user is already created, so won't pick up changes to /etc/skel
RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update > /dev/null && \
    apt-get install --no-install-recommends --yes \
        wget curl bzip2 ca-certificates \
        git \
        tini \
        > /dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    wget --no-hsts --quiet https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/${MINIFORGE_NAME}-${MINIFORGE_VERSION}-Linux-$(uname -m).sh -O /tmp/miniforge.sh && \
    /bin/bash /tmp/miniforge.sh -b -p ${CONDA_DIR} && \
    rm /tmp/miniforge.sh && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> /etc/skel/.bashrc && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> ~/.bashrc

# Downgrade libsqlite
# See https://github.com/iterative/dvc/issues/10692#issuecomment-2674679552
RUN conda install -y libsqlite=3.48.0 && \
    conda clean --tarballs --index-cache --packages --yes && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete && \
    conda clean --force-pkgs-dirs --all --yes

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/

# Install Pixi
ARG PIXI_VERSION=v0.69.0
RUN curl -L -o /usr/local/bin/pixi -fsSL --compressed "https://github.com/prefix-dev/pixi/releases/download/${PIXI_VERSION}/pixi-$(uname -m)-unknown-linux-musl" \
    && chmod +x /usr/local/bin/pixi \
    && pixi info

# Add init scripts
ENV INIT_SCRIPTS_DIR=/usr/local/share/devcontainer-init
RUN mkdir -p ${INIT_SCRIPTS_DIR}
COPY scripts/post-create.sh ${INIT_SCRIPTS_DIR}
COPY scripts/post-start.sh ${INIT_SCRIPTS_DIR}
COPY scripts/update-content.sh ${INIT_SCRIPTS_DIR}
COPY scripts/check-envs.sh ${INIT_SCRIPTS_DIR}

# Install Calkit
# Released images pin the version they were built for; local builds get
# whatever is latest on PyPI
ARG CALKIT_VERSION=
RUN uv pip install --system --no-cache-dir \
    "calkit-python${CALKIT_VERSION:+==${CALKIT_VERSION}}"
