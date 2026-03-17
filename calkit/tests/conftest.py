import pytest


@pytest.fixture
def tmp_dir(tmp_path, monkeypatch):
    """Fixture to change to a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path
