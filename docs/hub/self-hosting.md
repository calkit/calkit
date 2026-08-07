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

The CLI currently only knows how to talk to the built-in instances
(calkit.io, its staging environment, and a local development stack).
Support for pointing it at an arbitrary hub, including per-hub token
storage and API URL discovery, is in progress; a project will declare
which hub it belongs to via the `hub` key in `calkit.yaml`.
