# ADR 0001: Calkit Operators

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

- Status: accepted
- Date: 2026-09-26
- Issues: #1482 (MVP), #185, #90, #918
- User docs: [compute.md](../../compute.md)

## Context

Users want to work on a project on machines other than the one in front of
them, e.g., a lab workstation or an HPC cluster, without SSHing in and
juggling a second checkout.
Four issues ask for overlapping versions of this:

| Issue | Use case                                                              |
| ----- | --------------------------------------------------------------------- |
| #1482 | Workspaces on a machine, viewed and driven from the hub               |
| #185  | Running stages on other machines, asynchronously or in parallel       |
| #90   | Long-running or scheduled ops, device data collection, fleet rollouts |
| #918  | Compiling the pipeline to CI systems like Buildkite                   |

Two concrete use cases drive the MVP:

- An HPC user wants to see their jobs in the queue, read their logs, and
  notice when a stage times out so they can rerun it, without logging in
  to the cluster.
- A user wants to install the Operator on an office workstation and, from
  home or anywhere else with the hub, interact with a coding agent session
  running there and with the project in a shell.

The hub is meant to be cheap and lightweight to run,
which limits how much traffic it can relay.

Two pieces already exist:

- `system`, `slurm`, and `pbs` environments with a non-local `host` run
  stages over SSH in a managed workspace at
  `~/.calkit/workspaces/<hub>/<owner>/<name>`, moving a Git snapshot and
  DVC objects in and bringing changed outputs back, under a lock.
- `calkit local-server` is a localhost FastAPI app the hub's "local
  machine" tab calls for status, saving, pipeline runs, and Jupyter.

## Decision

### Scope

The MVP is #1482.
An Operator is a long-running Calkit process, one per machine and user
account, that manages workspaces on that machine and accepts commands from
the hub.
#185 and #90 must remain possible on top of this design but are not built
in it.
#918 is a CI integration and is not called an Operator.

The Operator replaces `calkit local-server` and the hub's "local machine"
tab completely.
The local server's endpoints become the Operator's first set of commands,
and the hub's "compute" views replace the tab.

### Transport

The Operator holds an outbound websocket to the hub, which relays traffic
between browsers and Operators.
This works behind NAT and firewalls without opening ports.
There is no direct or localhost path for now, even when the browser is on
the same machine.
SSH environments remain the way to run on other machines without the hub.

Relayed traffic is kept to what is interactive and small:

- Terminal traffic is keystrokes and screen output, typically a few KB/s
  while a session is active and nothing while idle.
  The Operator coalesces output into frames every few tens of
  milliseconds, and the websocket uses permessage-deflate, which matters
  for agent TUIs that redraw often.
- Structured commands, e.g., status, the scheduler queue, a page of logs,
  or a file opened in the editor, return small payloads.
  The relay enforces a maximum message size.
- Bulk data never goes through the relay.
  Outputs travel the way they already do, through Git and DVC to the
  project's storage, and large file downloads use presigned storage URLs.
  Port forwarding, e.g., to Jupyter or a web app, is out of scope.
- Status that only needs to be current to within minutes, e.g., liveness
  and scheduler job states, is reported by periodic HTTP check-ins, not
  held websockets, so an idle Operator costs the hub almost nothing.

The relay runs as its own single-process async service, not inside the
API's workers.
With the API's multiple workers, a browser and its Operator would often
land on different ones and have to meet through Valkey pub/sub on every
message.
A single process pairs them in memory and can be deployed, scaled, or
moved independently of the API.
The API issues short-lived tokens the relay verifies to pair a browser
with an Operator it's allowed to use.

The relay meters bytes per Operator from the start.
The Operator's command protocol is independent of transport, so if
metering shows the relay costs too much, a direct browser-to-Operator path
can be added with the relay handling only signaling, e.g., WebRTC data
channels, falling back to relaying when a peer-to-peer connection can't be
made.

### Authentication and permissions

`calkit install operator` registers the Operator with the hub using the
user's existing token and receives a dedicated Operator token, stored
locally.
That token can only connect as that Operator, so revoking it does not
affect the user's other tokens.

By default, only the Operator's owner can use it, and only inside
allowlisted workspaces:
discovered or registered personal workspaces and managed workspaces.
Within those, the owner can open shells and edit files.
The allowlist and other settings live in `~/.calkit/operator.yaml`.
Sharing with collaborators is out of scope for the MVP.

The Operator effectively gives the hub a shell on the machine, so the
user docs must say to install it only on accounts the user alone controls,
and that some HPC centers prohibit this kind of tunnel.

### Workspaces

There are two kinds:

- Personal workspaces are ordinary long-lived checkouts.
  The Operator discovers Calkit projects under `~/calkit`, and
  `calkit operator add-workspace <path>` registers ones elsewhere.
  These are the only kind edited from the hub.
- Managed workspaces are the existing hidden ones under
  `~/.calkit/workspaces`, checked out with `--force` and used for running
  stages.
  They are shown in the hub but not edited there.

### Sessions and the workspace view

The Operator owns its PTYs, so shell sessions, and any coding agent
running in one, survive browser disconnects.
Sessions end when closed explicitly or when the Operator restarts.
Windows uses ConPTY.

The hub's workspace view is built natively: xterm.js terminals over the
relay, the pipeline stage list, and a file tree with a simple editor.
We don't embed a full editor such as openvscode-server.

### Running as a service

`calkit install operator` installs a service that runs as the user and,
where allowed, starts at boot rather than at login.
This covers machines nobody logs in to, e.g., a cloud VM that is stopped
when not in use: when it starts again, so does the Operator.
Because the Operator only connects outbound, and its token and the
machine ID live on disk, a new IP address after a restart doesn't matter.
While a machine is off, the hub shows its Operator as offline with when it
was last seen.

- Linux: a `systemd --user` service with lingering enabled, so the user's
  services start at boot and survive logout.
  Installing enables lingering when permitted; otherwise it warns and
  prints the `sudo loginctl enable-linger` command.
- macOS: a LaunchDaemon with `UserName` set to the user when they have
  admin rights, otherwise a LaunchAgent that starts at login, with a
  warning.
- Windows: a scheduled task triggered at startup that runs whether or not
  the user is logged on, using S4U logon so no password is stored, when
  the user has admin rights, otherwise one triggered at login, with a
  warning.

Starting cloud VMs from the hub is out of scope.

On HPC, where login nodes kill long-lived processes, two modes are
supported:

- `calkit operator start` in the foreground, e.g., inside tmux.
- `calkit install operator --cron`, which checks in with the hub on a
  schedule, reporting scheduler job states, and opens the websocket only
  when there is work to do, e.g., the user has opened a shell.
  Its crontab includes an `@reboot` entry so it checks in at boot.

`scrontab` and similar are deferred.
Heavy work on HPC belongs in scheduler jobs, not on the login node.

### Scheduler jobs

The Operator exposes the existing `calkit scheduler queue`, `logs`, and
`cancel` behavior as structured commands, and reports job states,
including failures and timeouts, in its check-ins.
The hub shows these per workspace and can rerun a failed stage through
the Operator.

### CLI

- `calkit install operator [--ssh HOST] [--cron]` installs Calkit on the
  target if needed, then the Operator, then registers it.
  This widens `calkit install` from native dependencies to Calkit's own
  components.
- `calkit operator start|stop|status|logs|uninstall|add-workspace` manage
  the local Operator.
- `calkit hub get operators` lists a user's Operators from the hub.

### Removal

`calkit operator uninstall` removes the service and local state.
Deleting an Operator on the hub revokes its token and, if connected, tells
it to shut down.
A revoked Operator stops itself the next time it fails to connect.
The hub cannot uninstall anything from a machine that is offline.

### Configuration ownership

Operators belong to users and machines, not projects, so they are not
declared in `calkit.yaml`.
When stages can run through an Operator (phase 3), a project environment
will name one alongside or instead of `host`, e.g., `operator: my-hpc`,
reusing the existing snapshot, DVC transfer, and locking logic with the
relay as transport.
This avoids SSH keys, port forwarding, and repeated 2FA prompts on
clusters.

### Phases

1. Daemon, service install, registration, Operator token, hub compute tab
   with liveness, and the local server's features moved onto the relay.
2. Persistent terminals, the file tree and editor, and scheduler jobs.
3. Pipeline integration: `operator:` on environments, and LaTeX editor
   compiles through a workspace.
4. Sharing: collaborator workspaces and multiplayer.
5. Later: ops and fleet rollouts (#90), parallel `group` stages (#185).

## Consequences

- One hub-connected process now does what `calkit local-server` did, and
  more, so the local server and its hub tab are removed rather than
  maintained in parallel.
- The Operator requires the hub.
  The hub is still optional for the project itself, which lives in Git,
  and SSH environments still work without it.
- All interactive traffic passes through the relay, which costs latency
  and hub bandwidth.
  Keeping bulk data off the relay and metering it keeps that bounded, and
  a direct path can be added later without changing the Operator's
  command set.
- The hub gains a new service to deploy and monitor.
- The hub becomes a way to get a shell on users' machines, so the security
  of the hub, of user sessions, and of Operator tokens matters more than
  before.
- Personal and managed workspaces follow different rules, which the hub
  must make visible.

## Alternatives considered

- **Keep the local server alongside the Operator.** Two ways to do the
  same thing from the hub, one of which only works on localhost.
- **Direct or localhost connections from the browser.** Lower latency and
  no relayed traffic, but needs port exposure or WebRTC signaling plus a
  relay fallback anyway; deferred until metering shows it's needed.
- **Relaying inside the API workers.** No new service, but pairs across
  workers through Valkey pub/sub and competes with API requests.
- **Reuse the user's CLI token.** Revoking one Operator would revoke
  everything.
- **Zero permissions until approved on the machine.** Safer, but adds
  friction the owner-only allowlist mostly removes.
- **Embed openvscode-server.** Full-featured immediately, but heavy and
  hard to integrate with hub pages.
- **Sessions in tmux.** Would survive Operator restarts but adds a
  dependency and excludes Windows.
- **Declare Operators in `calkit.yaml`, as sketched in #90.** Ties a
  machine to a project; projects should name what they need and users
  should supply machines.
