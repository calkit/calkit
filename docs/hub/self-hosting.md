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
- A GitHub App.
  The hub manages project repos through GitHub,
  and creating a project currently requires a linked GitHub account,
  so this is the main piece of bring-your-own configuration.
  See [the section below](#the-github-app) for the permissions it needs.
- Object storage: the bundled MinIO works out of the box,
  or an external provider (calkit.io uses Google Cloud Storage)
  can be configured.
- Optionally, credentials for the outside integrations:
  Zenodo and Zotero apps, Stripe for paid plans, and Mixpanel for
  analytics. These can be left disabled for a lab-internal instance.

## The GitHub App

Users sign in through the App, and the hub acts on their behalf with the
user-to-server tokens it issues, so what the hub can do is exactly what
the App is granted.
There are no OAuth scopes to request separately:
a GitHub App's permissions are what its tokens carry.

Set the callback URL to the hub's login page,
e.g., `https://your-hub.example.edu/login`,
which is where GitHub sends users back with their authorization code.
Grant these permissions:

| Permission                 | Access       | Used for                                                       |
| -------------------------- | ------------ | -------------------------------------------------------------- |
| Repository: Metadata       | Read-only    | Required by GitHub for everything else                         |
| Repository: Administration | Read & write | Creating project repos, and adding and removing collaborators  |
| Repository: Contents       | Read & write | Reading and writing project files, branches, commits, releases |
| Repository: Issues         | Read & write | Project discussions, which are kept as issues and comments     |
| Repository: Pull requests  | Read-only    | Showing the state of a project's pull requests                 |
| Repository: Packages       | Read & write | Pushing and pulling Docker environment images to GHCR          |
| Organization: Members      | Read-only    | Checking which orgs a user belongs to                          |
| Account: Email addresses   | Read-only    | Matching a GitHub account to a hub user                        |

Set `GH_CLIENT_ID` and `GH_APP_PRIVATE_KEY` on the backend from the App's
client ID and a generated private key.
The two have to belong to the same App:
a mismatch shows up as a 401 from GitHub when the hub tries to mint an
installation token.

<!-- prettier-ignore -->
!!! note

    Packages access is what lets projects push Docker environment images to
    the GitHub Container Registry alongside their code. An instance that
    doesn't need that can leave it out, and image pushes will ask users for
    their own token with the `write:packages` scope instead.

### The push webhook

Everything a project page shows is worked out from its latest commit, and
for a large project that takes long enough to be worth doing before someone
opens the page rather than while they wait.
A push is when that work becomes necessary and when nobody is waiting, so
the hub asks GitHub to tell it about pushes.

The webhook belongs to the App, not to each repository:
set it once and every repo the App is installed on delivers to it.
In the App's settings, under **Webhook**:

- Tick **Active**.
- Set the URL to `https://api.your-hub.example.edu/events/github`.
- Set a secret, and give the backend the same value as `GH_WEBHOOK_SECRET`.
- Under **Subscribe to events**, tick **Push**.

Deliveries are rejected unless their signature matches `GH_WEBHOOK_SECRET`,
and an instance that hasn't set one refuses them outright, so there is no
unauthenticated way to make a hub do this work.

This is an optimization, not a requirement.
Leave the webhook off and pages still show the right thing;
the first person to open one after a push is the one who waits for it.
Warming needs the `worker` service and a `REDIS_URL` to queue onto,
both of which are in the bundled compose file.
The `rq-exporter` service reports what that queue is doing to Prometheus,
and the bundled Grafana has a **Warm queue** dashboard for it:
how deep the queue is, whether jobs are failing, and whether a worker is
alive at all.

<!-- prettier-ignore -->
!!! tip

    `calkit push` also tells the hub directly, so people pushing through the
    CLI get warmed pages whether or not the webhook is set up. That path
    covers repos GitHub can't call back on, such as a hub reachable only
    inside your network.

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
