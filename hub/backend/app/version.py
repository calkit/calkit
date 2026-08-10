"""The hub's own version.

Derived the way calkit-python derives its own: hatch-vcs reads it from the
Git tags at install time and writes it into the package metadata, which
``importlib.metadata`` reads back here. Releases are tagged ``hub/vX.Y.Z``
in a monorepo that also tags the Python package as ``vX.Y.Z``, so the tag
pattern in ``pyproject.toml`` is anchored on the prefix.

That covers the image too: its build bind-mounts ``.git`` into the install
step, so the metadata it ships is the release it was built from.

``HUB_VERSION`` overrides all of it, which development containers use. Their
virtualenv is baked into the image alongside everything else, so its
metadata is however many commits stale the image is, and rebuilding an
image to correct a version string is a poor trade.
"""

import functools
import logging
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as installed_version

from app.config import settings

logger = logging.getLogger("app")

TAG_PREFIX = "hub/v"
UNKNOWN = "unknown"
# What hatch-vcs falls back to when it is given a pretend version rather
# than a repository, which is what a build with no .git available produces
PLACEHOLDER = "0.0.0"


def normalize(version: str) -> str:
    """Strip the release tag's prefix, leaving the version users read."""
    version = version.strip()
    if version.startswith(TAG_PREFIX):
        return version[len(TAG_PREFIX) :]
    return version


def _from_metadata() -> str | None:
    """Read the version hatch-vcs wrote when the package was installed."""
    try:
        found = installed_version("app")
    except PackageNotFoundError:
        return None
    # An install that had no repository to read reports the pretend version
    # the image build supplies, which says nothing about the release
    if not found or found.startswith(PLACEHOLDER):
        return None
    return found


@functools.cache
def get_version() -> str:
    """Return the running hub's version, e.g. ``0.24.2``.

    Cached because a running process cannot change which version it is.
    """
    # The build argument first: where it is set, the metadata beside it is
    # the pretend version from a build that had no repository to read
    for source in (lambda: settings.HUB_VERSION or None, _from_metadata):
        found = source()
        if found:
            return normalize(found)
    # Not a failure worth an error: an image built without a version still
    # serves every request, it just can't name itself
    logger.info("Hub version is unknown; no build argument and no metadata")
    return UNKNOWN
