# Running your own hub

Like the rest of Calkit, the hub is free and open source, and the entire
stack lives in the
[`hub` directory of the calkit repo](https://github.com/calkit/calkit/tree/main/hub).
Self-hosting is possible, but is not yet a polished experience,
so expect to get your hands dirty.

## What the stack looks like

The hub runs as a Docker Compose stack:
a Traefik reverse proxy,
a FastAPI backend,
a React frontend,
a PostgreSQL database,
MinIO for object storage,
and Prometheus/Loki/Grafana for monitoring.

## What you'll need

- A host running Docker with a domain name pointed at it.
- A GitHub App and OAuth credentials.
  The hub manages project repos through GitHub,
  and creating a project currently requires a linked GitHub account,
  so this is the main piece of bring-your-own configuration.
- Object storage: the bundled MinIO works out of the box,
  or an external provider (calkit.io uses Google Cloud Storage)
  can be configured.
- Optionally, credentials for the outside integrations:
  Zenodo and Zotero apps, Stripe for paid plans, and Mixpanel for
  analytics. These can be left disabled for a lab-internal instance.

## Where to start

The operational details, including environment variables, Traefik setup,
and continuous deployment, live with the code in
[the deployment notes](https://github.com/calkit/calkit/blob/main/hub/docs/dev/deployment.md).

## Connecting the CLI

The CLI shares one configuration across hubs, with credentials (tokens)
scoped per hub. `calkit hub config set token ... --hub
your-hub.example.edu` operates on a specific hub's credentials, and the
`CALKIT_HUB` environment variable selects the active hub for other
commands.

A hub's URL is all that's needed to connect to it:

```sh
export CALKIT_HUB=https://your-hub.example.edu
```

This works because of the rule below, which every instance is expected to
follow. There's no separate API URL to configure.

## Serve the API from the `api` subdomain

**A hub must serve its API from the `api` subdomain of the host serving
its web app.** A hub at `https://your-hub.example.edu` serves its API at
`https://api.your-hub.example.edu`, which is how calkit.io
(`api.calkit.io`) and the staging instance
(`api.staging.calkit.io`) are set up.

This is a requirement, not a suggestion. Clients derive the API URL from
the hub URL, so an instance that puts its API somewhere else can't be
reached by the CLI, the browser extension, or anything else that only
knows the hub's URL. Point both hostnames at the same Traefik instance
and let it route by host.

<!-- prettier-ignore -->
!!! note

    The local development stack predates this rule and doesn't follow it:
    its web app is at `http://localhost:5173` while its API is at
    `http://api.localhost`. Built-in environments carry explicit URLs for
    that reason, so only self-hosted instances rely on the rule.

If an instance genuinely can't follow the convention, the
`CALKIT_HUB_API_BASE_URL` environment variable still overrides the
derived URL for the CLI:

```sh
export CALKIT_HUB=https://your-hub.example.edu
export CALKIT_HUB_API_BASE_URL=https://calkit-api.example.edu
```

Treat that as an escape hatch. Other clients have no equivalent, so an
instance relying on it won't work with all of them.
