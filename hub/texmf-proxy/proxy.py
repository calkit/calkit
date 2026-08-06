#!/usr/bin/env python3
"""On-demand TeX Live file proxy for the in-browser (busytex/WASM) compiler.

The WASM engine ships only a curated subset of TeX Live and can't generate
bitmap fonts (mktexpk needs fork(), which the runtime lacks). On any kpathsea
miss it does a synchronous fetch of GET {VITE_TEXMF_PROXY}/f/<name>; this
service resolves <name> against a full TeX Live install (via kpsewhich, with
-mktex=pk/-mktex=tfm so fonts and metrics are generated where fork() works) and
returns the bytes. That gives the preview full TeX Live coverage, one file at a
time, without bundling all of TeX Live into the browser.

Runs inside a full-TeX-Live image, so kpsewhich is called locally (no docker
exec). Configured via env: TEXMF_PROXY_PORT (default 8771) and
TEXMF_PROXY_ALLOW_ORIGIN (CORS, default "*"; set to the site origin in prod).
"""
import os
import subprocess
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("TEXMF_PROXY_PORT", "8771"))
ALLOW_ORIGIN = os.environ.get("TEXMF_PROXY_ALLOW_ORIGIN", "*")


def resolve(name: str) -> bytes | None:
    # The engine only ever asks for bare filenames; refuse anything else so a
    # crafted name can't reach outside the TeX tree.
    if not name or "/" in name or ".." in name:
        return None
    try:
        path = subprocess.check_output(
            ["kpsewhich", "-mktex=pk", "-mktex=tfm", name],
            text=True,
            timeout=60,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", ALLOW_ORIGIN)

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if not self.path.startswith("/f/"):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        name = urllib.parse.unquote(self.path[len("/f/"):])
        data = resolve(name)
        if data is None:
            self.send_response(404)
            self._cors()
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"{self.command} {self.path}", flush=True)


if __name__ == "__main__":
    print(f"texmf proxy on :{PORT} (GET /f/<name>)", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
