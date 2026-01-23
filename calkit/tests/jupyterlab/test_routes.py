"""Tests for JupyterLab extension server routes."""

import json
import os


async def test_hello(jp_fetch):
    # Save current working directory to prevent test interference
    original_cwd = os.getcwd()
    try:
        response = await jp_fetch("calkit", "hello")
        assert response.code == 200
        payload = json.loads(response.body)
        assert payload == {
            "data": (
                "Hello, world!"
                " This is the '/calkit/hello' endpoint."
                " Try visiting me in your browser!"
            ),
        }
    finally:
        # Restore working directory
        os.chdir(original_cwd)
