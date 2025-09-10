"""Functionality for working with Docker."""

MINIFORGE_LAYER_TXT = r"""
# Install Miniforge
ARG MINIFORGE_NAME=Miniforge3
ARG MINIFORGE_VERSION=24.9.2-0
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
RUN apt-get update > /dev/null && \
    apt-get install --no-install-recommends --yes \
        wget bzip2 ca-certificates \
        git \
        tini \
        > /dev/null && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    wget --no-hsts --quiet https://github.com/conda-forge/miniforge/releases/download/${MINIFORGE_VERSION}/${MINIFORGE_NAME}-${MINIFORGE_VERSION}-Linux-$(uname -m).sh -O /tmp/miniforge.sh && \
    /bin/bash /tmp/miniforge.sh -b -p ${CONDA_DIR} && \
    rm /tmp/miniforge.sh && \
    conda clean --tarballs --index-cache --packages --yes && \
    find ${CONDA_DIR} -follow -type f -name '*.a' -delete && \
    find ${CONDA_DIR} -follow -type f -name '*.pyc' -delete && \
    conda clean --force-pkgs-dirs --all --yes  && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> /etc/skel/.bashrc && \
    echo ". ${CONDA_DIR}/etc/profile.d/conda.sh && conda activate base" >> ~/.bashrc
""".strip()

FOAMPY_LAYER_TEXT = r"""
RUN pip install --no-cache-dir numpy pandas matplotlib h5py \
    && pip install --no-cache-dir scipy \
    && pip install --no-cache-dir foampy
""".strip()

UV_LAYER_TEXT = """
COPY --from=ghcr.io/astral-sh/uv:0.8.5 /uv /uvx /bin/
"""

JULIA_LAYER_TEXT = """
# Install Julia
# Ensure base image is a bullseye distribution
COPY --from=julia:1.11.6-bullseye /usr/local/julia /usr/local/julia
ENV JULIA_PATH=/usr/local/julia \
    PATH=$PATH:/usr/local/julia/bin \
    JULIA_GPG=3673DF529D9049477F76B37566E3C7DC03D6E495 \
    JULIA_VERSION=1.11.6
"""

LAYERS = {
    "mambaforge": MINIFORGE_LAYER_TXT,
    "miniforge": MINIFORGE_LAYER_TXT,
    "foampy": FOAMPY_LAYER_TEXT,
    "uv": UV_LAYER_TEXT,
    "julia": JULIA_LAYER_TEXT,
}
