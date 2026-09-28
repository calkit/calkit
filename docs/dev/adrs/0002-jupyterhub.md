# ADR 0002: Calkit on JupyterHub

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

- Status: proposed
- Date: 2026-09-27
- Builds on: [ADR 0001](0001-operators.md)

## Context

JupyterHub gives users compute and storage, often with their institution's
login, on a lab server, a Kubernetes cluster, or an HPC cluster, where
batchspawner runs each user's server as a job on a compute node.
What it doesn't give them is structure or connections:

- A server comes up attached to a home directory and nothing else.
  Users invent their own layout, and nothing ties a directory of notebooks
  to a project, its environments, its data, or its paper.
- Each project may need different environments, but the server offers
  whatever kernels were installed, so projects end up sharing one.
- A server isn't connected to other services.
  Getting work out means setting up Git credentials, storage for data,
  and so on by hand, on every hub, so analysis tends to stay on the hub's
  disk, siloed from data collection, planning, and writing.

Calkit's aim is to connect those stages in one project, with Git as the
record, and the hub as where they come together.
JupyterHub is a common place for the analysis stage to happen, so Calkit
should work well inside it.

ADR 0001 also left open how a shared machine should give each person their
own access.
An Operator running as root to create per-user accounts would be a large
risk.
JupyterHub has already solved this: it authenticates users and starts each
one's server as that user.

## Decision

### An Operator inside each user's server

A user's Jupyter server runs an Operator as that user, alongside the
server, started by the Jupyter server extension that `calkit-python`
already ships.
It uses the same protocol, relay, owner-only access, and two-factor
requirements as any other Operator.

- The first time, the JupyterLab extension offers to connect the server
  to Calkit, using the device login flow, and registers an Operator.
  Its config goes in the user's home directory, which persists across
  spawns, so later servers connect on their own, even on a different pod
  or node.
- It runs in a new `jupyter` mode: started when the server starts and
  stopped when it stops, with no service, cron job, or lock file across
  servers to manage.
  While the server is down, the hub shows the Operator as asleep.
- Idle culling judges activity by Jupyter's own traffic, so the Operator
  reports open sessions to the server as activity, within whatever limits
  the hub sets, rather than letting a running agent session be culled.
- Waking a stopped server from the Calkit hub would need a JupyterHub API
  token, stored encrypted like other external credentials.
  This is optional; without it, the user starts their server as usual.

Hub users get their own servers as themselves, so this is also how a
shared machine running JupyterHub gives each person access, without an
Operator running as root.
Machines without JupyterHub use one Operator per user account, as in
ADR 0001.

### Projects, not a bare home directory

The JupyterLab extension shows the user's Calkit projects under `~/calkit`
as the starting point, rather than only a file tree.
A notebook opened in a project runs with an environment the project
declares, so each project keeps its own environments instead of sharing
the server's.
Work is committed and pushed like on any other machine, so the server is
one workspace among the user's others, not the only copy.

### Connections through the Calkit hub

A server connected to Calkit gets the connections a bare server lacks,
brokered by the Calkit hub, so pushing work out takes no setup on the
JupyterHub:

- Git: a credential helper asks the Calkit hub for a short-lived token
  scoped to the project's repository, e.g., a GitHub App installation
  token, rather than storing a long-lived one on the server.
- Data: the project's DVC remote on the Calkit hub, authenticated for that
  project.
- Other services the user has connected on the Calkit hub, e.g., Overleaf,
  Zotero, and Zenodo, used through the project rather than set up again.

The Operator's token gains scopes for these, limited to the projects whose
workspaces are on it and to tokens that expire quickly.
This is the same extension ADR 0001 anticipates for loops, which need to
push data from machines, and it keeps the user's own login off the
server.

### Distribution

- An image for Kubernetes and Docker based hubs, e.g., Zero to
  JupyterHub, built from `images/jupyter` alongside `images/latex`.
  It includes Calkit with both extensions, uv, pixi, and conda, and a TeX
  installation, so LaTeX builds work without a container runtime.
- For hubs where the admin controls the environment, e.g., on HPC, or
  where users install into their own, the plugin is `calkit-python`
  itself, whose server extension does the rest.

### Container runtimes

Only environments of kind `docker` need a container runtime, including
Calkit's default LaTeX environment; uv, venv, conda, pixi, Julia, and R
environments work in an ordinary server.
Docker in Docker needs privileged pods, which most hubs won't allow, so
Calkit won't depend on it.
Instead:

- Operators report the container runtimes available to them when they
  check in, so the hub can say why a stage can't run somewhere rather than
  failing partway through.
- `docker` environments can run with Apptainer where Docker isn't
  available, which is usual on HPC clusters and doesn't need root.
- Stages that need a container can run on another of the user's Operators
  that has one, through the routing by host planned in ADR 0001.
- Hub admins who want containers in servers can enable rootless Podman or
  Sysbox, which Calkit will use if present.

## Consequences

- Calkit becomes a project layer that research computing groups can add to
  a JupyterHub by changing the server image or installing a package.
- The Calkit hub holds more responsibility for credentials, handing out
  short-lived, scoped tokens to Operators, which makes the security of
  Operator tokens and the hub matter more.
- The `jupyter` mode's lifecycle differs from service and cron modes, e.g.,
  batchspawner servers end with their job's walltime, which the hub should
  show.
- Running containers inside servers stays up to each hub's admins.

## Alternatives considered

- **The Calkit hub talking to JupyterHub directly, with nothing installed**
  in the server, bridging its terminals and files through the relay.
  This needs no install, but the Calkit hub would hold a long-lived
  credential for the user's account, many institutional hubs aren't
  reachable from outside, and pipelines and status still need Calkit in the
  server anyway.
- **An Operator running as root on shared machines**, creating accounts for
  users, which puts a root process behind commands from the internet.
  JupyterHub's spawning already gives each user their own account.
- **Requiring Docker in Docker**, which needs privileged pods most hubs
  won't allow.
