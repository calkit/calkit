# texmf-proxy

On-demand TeX Live file server for the in-browser LaTeX preview.

The browser compiler (busytex/WASM in `frontend/public/tex`) ships only a subset
of TeX Live and can't generate bitmap fonts (`mktexpk` needs `fork()`). When it
hits a missing file it synchronously fetches `GET {VITE_TEXMF_PROXY}/f/<name>`.
This service resolves `<name>` against a full TeX Live install with `kpsewhich`
(generating PK/TFM fonts where `fork()` works) and returns the bytes, giving the
preview full TeX Live coverage one file at a time, e.g. `revtex4-1.cls` for
AASTeX documents.

## Run

Started as the `texmf-proxy` service by `make dev` / `docker compose up`. In dev
it's exposed on `localhost:8771` and the frontend points at it via
`VITE_TEXMF_PROXY` (see `docker-compose.override.yml`).

Quick check:

```bash
curl -sf http://localhost:8771/f/revtex4-1.cls | head
curl -sf http://localhost:8771/health
```

## Config

- `TEXMF_PROXY_PORT` (default `8771`)
- `TEXMF_PROXY_ALLOW_ORIGIN` (CORS; default `*`, set to the site origin in prod)

## Notes

Only bare filenames are served (no paths, no `..`). The base image is a rolling
full TeX Live; the WASM engine is TeX Live 2023, but class/style/font sources are
version-agnostic. Pin `TEXLIVE_IMAGE` by digest for strict reproducibility.
