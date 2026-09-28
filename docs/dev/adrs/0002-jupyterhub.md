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
JupyterHub is a common place for the analysis stage to happen, so a user
should be able to add their JupyterHub account as an Operator on the
Calkit hub, then open a project there, with a shell and agent sessions,
like any other machine.

This has to work without much from the JupyterHub's admins, who users often
don't control, e.g., at an HPC center.
It also helps with a question ADR 0001 left open, how a shared machine
gives each person their own access: JupyterHub already authenticates users
and starts each one's server as that user, so no Operator needs root.

## Decision

### Adding a JupyterHub as an Operator

On the Calkit hub, adding an Operator offers a JupyterHub kind, which takes
the JupyterHub's URL and connects in one of two ways.

**Automatic**, with a JupyterHub API token the user creates for their own
account, with scopes limited to starting and accessing their own servers
and an expiry.
The Calkit hub stores it encrypted and uses it only server side, to:

1. Start the user's server through the JupyterHub REST API, if it isn't
   running.
2. Open a terminal in it through the Jupyter Server API and run Calkit's
   install script with a registration code (see below), which installs
   Calkit in the user's home directory and the startup hook that runs the
   Operator whenever the server starts.

From then on it's an ordinary Operator: it connects to the relay itself,
with owner-only access and two-factor authentication as in ADR 0001.
The token is used again only to start a stopped server when the user opens
a project on it, so the Operator is never merely asleep.

**Manual**, for JupyterHubs the Calkit hub can't reach, e.g., behind a VPN,
or for users who'd rather not store a token: the screen shows a command to
paste into a terminal on the JupyterHub, with a registration code, which
does the same installation.
Nothing is stored on the Calkit hub, and servers are started on the
JupyterHub as usual.

Neither needs anything from the JupyterHub's admins beyond what users can
normally do: create tokens for themselves, start their own servers, open
terminals, install software in their home directory, and configure their
own Jupyter server.
Installing Calkit needs outbound internet access from the server.

### Registration codes

Registering an Operator currently needs the user's Calkit login on that
machine, which an automated setup can't provide, and which shouldn't be
left on a shared server anyway.
Instead, the Calkit hub can mint a registration code, from a signed-in
session that has entered a second factor recently, which is single use and
expires within minutes.
`calkit operator install --code <code>` exchanges it for an Operator token
without the user's login ever reaching the machine.
This applies to Operators installed any way, e.g., over SSH, not just on
JupyterHub.

### The Operator's lifecycle in a server

The Operator runs in a new `jupyter` mode, started by a hook in the user's
own `~/.jupyter/jupyter_server_config.py`, which Jupyter runs when the
server starts, and exiting when the server does.
It needs no service, cron job, or change to the server's environment, so
Calkit can be installed as a standalone tool, e.g., with uv.

- Its config is in the user's home directory, which persists across
  spawns, so each new server reconnects as the same Operator, even on a
  different pod or node.
- Idle culling judges activity by Jupyter's own traffic, so the Operator
  reports open sessions to its server as activity, within whatever limits
  the hub sets, rather than letting a running agent session be culled.
- Batchspawner servers end with their job's walltime, which the Calkit hub
  shows alongside the Operator.

### One server per project

Where the JupyterHub allows named servers, each project gets its own
server, named after it, with its own Operator, identified by
`JUPYTERHUB_SERVER_NAME` and scoped to that project's workspace, which it
clones when it first starts.
Opening a shell in a project from the Calkit hub starts or reuses that
project's server.
Without named servers, a user's one server has one Operator covering their
projects in `~/calkit`, as on any other machine.

Two limits apply without help from admins:

- Calkit can't set a server's root directory, so JupyterLab's file browser
  still shows the whole home directory, while Calkit's sessions and actions
  are scoped to the project.
- Named servers usually share the user's home volume, so one server per
  project gives structure and a scope for each Operator, not isolation
  between projects.

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

### What admins can add

None of these are required, but each makes Calkit work better on a hub:

- Enabling named servers, for one server per project.
- An image with Calkit preinstalled, built from `images/jupyter` alongside
  `images/latex`, with both of its Jupyter extensions, uv, pixi, conda, and
  a TeX installation, so servers start faster and LaTeX builds work without
  a container runtime.
  With Calkit in the server's own environment, the JupyterLab extension
  can also show projects rather than a bare home directory, and default
  each notebook to an environment its project declares.
- A spawner hook, e.g., a `calkit-jupyterhub` package, that enforces one
  server per project by refusing spawns that don't name one, sets each
  server's root directory to its project, and picks its image or
  environment from the project's specs.

### Expensive compute

JupyterHub doesn't dispatch work anywhere.
It sizes each user's server when it starts, from a menu its admins
define, e.g., KubeSpawner profiles mapped to resource requests, or
batchspawner and Open OnDemand forms choosing a partition, GPUs, and
walltime for a job the whole server runs in.
The server is the unit of compute, sized for the heaviest thing it will
do and holding those resources while idle, and sending work elsewhere is
left to add-ons its admins deploy, e.g., Dask Gateway.

Calkit keeps compute requirements in the project instead: a stage's
environment names where it runs, e.g., a `slurm` environment with a
`host`, and the stage's scheduler options say what it needs.
So a JupyterHub server can stay small, for interactive work, while
`calkit run` sends heavy stages where the project says:

- From a server on the cluster itself, e.g., under batchspawner, a
  `slurm` environment submits jobs from there, where the center allows
  submitting from compute nodes.
- From a server elsewhere, e.g., on a Kubernetes hub while the GPUs are on
  an HPC cluster, a stage reaches the cluster through the user's Operator
  there, by the routing by host planned in ADR 0001, with no SSH keys on
  the server and no repeated second factor prompts.
- With detached remote stages, also planned in ADR 0001, the server
  needn't stay up while a cluster job runs; the Operator on the cluster
  pushes the results when it finishes.

This follows from Calkit's general approach of giving users control and
keeping configuration in the project rather than the infrastructure:
where each stage runs and what it needs are versioned with the project,
so it runs the same way from any workspace, and admins needn't maintain a
server option for every project's needs.
Quotas, queues, and allocations still belong to the infrastructure, and
jobs run as the user, on their own allocation.
Running stages somewhere else is an explicit change to the project's
environments rather than a per-user override, so where each stage ran is
always versioned; switching among clusters a project already declares is
proposed in #1743.

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

- Users can bring their JupyterHub accounts into Calkit themselves, without
  waiting on admins, and admins who want a better experience can add an
  image or a spawner hook.
- With automatic setup, the Calkit hub holds a JupyterHub token for the
  user's account, which ADR 0001 otherwise avoids for machines.
  It's limited by the token's scopes and expiry, stored encrypted, and
  used only when a signed-in session with a recent second factor asks.
  Manual setup remains for those who don't want that.
- The Calkit hub hands out more short-lived, scoped credentials, to
  Operators for Git, data, and other services, which makes the security of
  Operator tokens and the hub matter more.
- Registration codes replace putting the user's login on machines when
  installing Operators, anywhere.
- Running containers inside servers stays up to each hub's admins.
- Heavy compute follows the project rather than the server, which depends
  on ADR 0001's routing by host and detached remote stages for servers that
  aren't on the cluster.

## Alternatives considered

- **The Calkit hub driving JupyterHub directly with nothing installed**,
  bridging its terminals and files through the relay for good.
  The automatic setup uses the JupyterHub API only to start servers and
  install Calkit, because pipelines, status, and workspace actions need
  Calkit in the server anyway, and a permanent bridge would route all
  traffic through the Calkit hub with a stored token.
- **Registering the Calkit hub as a JupyterHub OAuth service**, which is
  cleaner than users creating tokens but needs each hub's admins to
  configure it.
- **Requiring an admin-installed image or spawner hook**, which would leave
  users on hubs whose admins won't change them without Calkit.
- **An Operator running as root on shared machines**, creating accounts for
  users, which puts a root process behind commands from the internet.
- **Requiring Docker in Docker**, which needs privileged pods most hubs
  won't allow.
