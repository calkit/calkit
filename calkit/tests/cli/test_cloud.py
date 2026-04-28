"""Tests for the cloud CLI."""

import calkit.cli.cloud as cloud_cli


def test_cloud_login_already_logged_in(monkeypatch, capsys):
    def _get(path):
        assert path == "/user"
        return {"email": "user@example.com"}

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    cloud_cli.login()
    out = capsys.readouterr().out
    assert "Device is already authenticated." in out


def test_cloud_login_device_flow_success(monkeypatch, capsys):
    call_counts = {"token_polls": 0}
    post_calls = []

    class DummyConfig:
        def __init__(self):
            self.token = None
            self.written = False

        def write(self):
            self.written = True

    cfg = DummyConfig()

    def _get(path):
        assert path == "/user"
        raise RuntimeError("401: Not authenticated")

    def _post(path, **kwargs):
        post_calls.append((path, kwargs))
        if path == "/login/device":
            return {
                "device_code": "dev-123",
                "verification_uri": (
                    "https://app.example.com/cli-auth?device_code=dev-123"
                ),
                "expires_in": 60,
                "interval": 1,
            }
        if path == "/login/device/token":
            call_counts["token_polls"] += 1
            if call_counts["token_polls"] < 2:
                return {"detail": "Authorization pending"}
            return {"access_token": "ckp_test_token"}
        raise AssertionError(f"Unexpected path: {path}")

    monkeypatch.setattr(cloud_cli.calkit.cloud, "get", _get)
    monkeypatch.setattr(cloud_cli.calkit.cloud, "post", _post)
    monkeypatch.setattr(cloud_cli.calkit.config, "read", lambda: cfg)
    monkeypatch.setattr(cloud_cli.webbrowser, "open", lambda _url: True)
    monkeypatch.setattr(cloud_cli.time, "sleep", lambda _seconds: None)
    cloud_cli.login()
    out = capsys.readouterr().out
    assert "Authorize this device by opening this URL:" in out
    assert "Waiting for authorization..." in out
    assert "Logged in successfully." in out
    assert cfg.token == "ckp_test_token"
    assert cfg.written is True
    assert post_calls[0][0] == "/login/device"
    assert post_calls[0][1].get("auth") is False
    assert post_calls[1][0] == "/login/device/token"
    assert post_calls[1][1].get("auth") is False
