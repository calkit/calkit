"""Tests for app.version."""

from unittest.mock import patch

from app import version


def _uncached() -> str:
    version.get_version.cache_clear()
    try:
        return version.get_version()
    finally:
        version.get_version.cache_clear()


def test_normalize_strips_the_release_prefix() -> None:
    """The tag names the hub; the version shown to users doesn't."""
    assert version.normalize("hub/v0.24.2") == "0.24.2"
    assert version.normalize("0.24.2") == "0.24.2"
    # A development checkout describes as tag-distance-commit
    assert version.normalize("hub/v0.24.2-30-ged59079") == "0.24.2-30-ged59079"


def test_build_argument_wins() -> None:
    """A container's metadata is a pretend version, so it can't be trusted.

    The image build has no repository to read, and the pretend version it
    falls back to cannot be aimed at this package alone.
    """
    with patch.object(version.settings, "HUB_VERSION", "hub/v1.2.3"):
        with patch.object(version, "_from_metadata", return_value="9.9.9"):
            assert _uncached() == "1.2.3"


def test_falls_back_to_installed_metadata() -> None:
    """What hatch-vcs recorded wherever the package was installed from a
    checkout rather than built inside the image."""
    with patch.object(version.settings, "HUB_VERSION", ""):
        with patch.object(version, "_from_metadata", return_value="0.24.2"):
            assert _uncached() == "0.24.2"


def test_unknown_when_nothing_can_say() -> None:
    """An image with no version still serves every other request."""
    with patch.object(version.settings, "HUB_VERSION", ""):
        with patch.object(version, "_from_metadata", return_value=None):
            assert _uncached() == version.UNKNOWN


def test_metadata_ignores_the_pretend_version() -> None:
    """A build with no repository reports 0.0.0, which is not a release."""
    with patch.object(version, "installed_version", return_value="0.0.0"):
        assert version._from_metadata() is None
    with patch.object(version, "installed_version", return_value="0.24.2"):
        assert version._from_metadata() == "0.24.2"
