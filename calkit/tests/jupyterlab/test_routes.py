"""Tests for JupyterLab extension server routes."""

import json


async def test_hello(jp_fetch):
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
