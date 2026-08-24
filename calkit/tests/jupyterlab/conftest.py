import pytest


@pytest.fixture
def jp_server_config(jp_server_config):
    # Load the Calkit server extension in the test Jupyter server.
    return {"ServerApp": {"jpserver_extensions": {"calkit": True}}}
