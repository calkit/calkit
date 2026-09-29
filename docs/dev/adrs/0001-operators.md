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

The core problem is reaching a project on another machine without a VPN
and SSH, e.g., through VS Code's remote features.
Tools that control a coding agent remotely solve part of it, but they give
no shell, only work with one agent, and organize everything around agents
rather than projects.
The Operator should instead show one project and all of its parts in one
place: its workspaces, a shell, and sessions of whichever coding agents
the user runs.

Two concrete use cases drive the MVP:

- An HPC user wants to see their jobs in the queue, read their logs, and
  notice when a stage times out so they can rerun it, without logging in
  to the cluster.
- A user wants to install the Operator on an office workstation and, from
  home or anywhere else with the hub, interact with a coding agent session
  running there and with the project in a shell.

A third shapes the design beyond the MVP:
a user drives a project's pipeline from a laptop, with GPU stages running
as SLURM jobs on a cluster, while a coding agent works in a separate
checkout on that cluster.
Eventually they want to work on it hub first: go to the project on the hub,
join the agent session, open a shell, edit files, and run stages, without
thinking about which machine does what.

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

`calkit operator install` registers the Operator with the hub using the
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

The Operator effectively gives the hub a shell on the machine, and
bypassing a VPN is the point, so the hub account becomes the only barrier
in front of those machines.
Opening sessions on an Operator therefore requires two-factor
authentication on the hub account.
The hub had none, so it's a step-up check rather than part of logging in:
the user sets up an authenticator app (TOTP), and getting a browser relay
token takes a code from it entered within the last 12 hours.
Codes can't be reused, and repeated wrong ones lock verification for a
few minutes.

A security review found that a check on the account alone doesn't stop
a leaked credential, e.g., a personal access token in a CI secret or a
DVC token sent to a remote a repo controls, so it's tightened three ways:

- Proof of entering a code belongs to the session that entered it: a
  short-lived token it sends with requests, not a record on the account.
- Getting a relay token or managing two-factor authentication takes a
  signed-in session, and personal access tokens are refused, as are
  scoped ones anywhere outside their scope.
- Setting up an authenticator app takes a code emailed to the user as
  well as one from the app, so a leaked credential can't add an
  attacker's.

A second review looked for any way around those and tightened them
further:

- A signed-in session means a person signing in to the web app, recorded
  on the refresh tokens of that sign-in, rather than any token that isn't
  a personal access token.
  CLI, CI, and GitHub token logins, and tokens from emailed links, don't
  count, and authorizing a CLI login takes a signed-in session, so a
  personal access token can't be traded for one.
  The proof of a second factor names the session, and changing or
  resetting the password ends every other session.
- Changing a verified email takes a code sent to it, and setting up an
  authenticator app or registering an Operator takes a verified email,
  so a stolen session can't move the account to an attacker's inbox and
  set up their app.
  A Google sign-in that claims an account whose email was never verified
  resets whatever someone else could have set up on it.
- Code checks lock their row, so parallel guesses can't get past the
  limit.
- The relay signs with a key of its own, since it's exposed to the
  internet, and takes tokens in a message rather than the URL, once each.
- The Operator doesn't take the relay's word for who opened a channel.
  The API signs a grant for each browser connection, naming the Operator
  and its owner, with an Ed25519 key only it holds, and the Operator
  checks it against the public key it pinned when it registered, using
  each grant once.
  So the relay alone can't open channels, for shells or anything else,
  and what's left to trust is the API itself, as with any web terminal
  its pages serve.
- The Operator registers with the user's own hub, never one named by a
  project in the working directory, and refuses to connect without TLS
  except locally or to run as root.
  Paths and clone URLs from the hub have to be plain ones, so they can't
  be taken as options or reach outside the workspace.
- Links built from project data only allow web and email URLs, since a
  `javascript:` URL in a project's `calkit.yaml` would otherwise run in
  the owner's browser, where it could reach their Operators.
  Passkeys can be added later as another way to satisfy the same check.
  The user docs must say prominently to install the Operator only on
  accounts the user alone controls, and to check institutional policy
  first, since this is equivalent to a VS Code tunnel, which some
  institutions and HPC centers prohibit.

Shell sessions aren't confined to workspaces.
Only an Operator's owner can open them, and the owner already has a shell
on their own machine, so hiding the rest of it would cost usability,
e.g., toolchains, Git credentials, and agent configs in the home
directory, without protecting anything from them.
Confinement is planned for when others can open sessions on someone's
machine, i.e., organization Operators and shared workspaces: each user
isolated as a separate OS account or in a container, with filesystem
restrictions on top, i.e., Landlock on Linux and `sandbox-exec` on macOS,
allowing system paths, the workspace, and a configurable list of home
paths, and refusing sessions where they can't be enforced.

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

### Workspace status

Check-ins carry only what's cheap to get for every workspace every minute:
branch, commit, whether there are uncommitted changes, how far it is from
its remote, and the pipeline's run state.
That's whether a live process holds DVC's lock, which stages are running
and since when, from the run's log, and how the latest run ended, from
the record `calkit run` leaves.
The hub shows these without connecting to the Operator or asking for a
second factor, so someone who only wants to know whether a run is going
or failed doesn't need a session.
The full status, i.e., stale stages and why, running stages, and changed
files and data, comes from `calkit status --json`, the same source as the
VS Code extension's sidebar.
It's too expensive to compute continuously, so the Operator runs it when
someone opens the workspace in the hub, which then follows it while a run
is in progress.

### Multiple workspaces per project

A project can have many workspaces across a user's Operators, e.g., a
laptop checkout, a personal checkout on a cluster, and a managed workspace
on the same cluster.

Git and DVC remain the only way state moves between workspaces.
There is no live file sync between them.
Each pipeline run has a single workspace driving it, and its results
reach the others through commits, pushes, pulls, and DVC.
This is how the laptop and managed workspaces already interact, and it is
the only model that stays predictable with an agent editing in one
workspace while stages run from another.
The hub makes divergence visible instead of hiding it: its compute page
lists every workspace of the project with its commit, whether it has
uncommitted changes, and how far ahead of or behind the hub it is, plus the
sessions running in it.

To avoid paying twice for expensive stages, the Operator points all of a
project's workspaces on one machine at a shared DVC cache, so the run cache
lets one workspace restore outputs another has already computed instead of
recomputing them.
A lock keyed on the stage and its input hashes, held while a stage runs on
that machine, makes a second request for the same computation wait for the
first instead of submitting its own job.

### Sessions and the workspace view

The Operator owns its PTYs, so shell sessions, and any coding agent
running in one, survive browser disconnects.
Sessions end when closed explicitly or when the Operator restarts.
Windows uses ConPTY.

Every session is a login shell in the workspace, so it has the user's
full environment, e.g., `PATH` additions and modules, as with SSH.
Users run whichever coding agent they like from it, and get the shell back
when the agent exits.
The hub labels each session by its terminal's foreground process, e.g.,
`claude` or `bash`, falling back to "shell" on Windows.
Agent-specific features are deferred:

- An optional command to run when a session starts.

- Notifications when an agent is waiting for input, detected from the
  terminal bell or OSC 9/777 escape sequences in its output.
- A chat view of a session, better suited to phones than a terminal, via
  the Agent Client Protocol (ACP), which several agents support natively
  or through adapters.
  This is the one feature that needs the Operator to launch the agent
  itself, in ACP mode rather than as a TUI.
  Terminals remain the baseline, since they work with every agent.

The hub's workspace view is built natively: xterm.js terminals over the
relay, the pipeline stage list, and a file tree with a simple editor.
We don't embed a full editor such as openvscode-server.

The editor works on the workspace's files directly through the Operator,
the way a remote editor does, not through Git.
Saving writes the file in the workspace; committing and pushing are
separate, explicit actions.
Conflicts with an agent editing the same file are handled as a local
editor would handle them:
an open file with no unsaved edits reloads when it changes on disk, and
saving over a file that changed since it was opened asks before
overwriting.
Git carries changes between workspaces, not between the editor and the
workspace it's open in.

Editing the hub's copy of a project, i.e., what has been pushed, commits
directly, which workspaces then need to pull.
When the user has a live workspace for the project, the hub opens files
there by default, and each user can choose a default workspace per
project, which the hub opens into when working hub first.

### Running as a service

`calkit operator install` installs a service that runs as the user and,
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
- Windows: a script in the user's Startup folder that starts it hidden at
  login, which needs no admin rights.
  Starting at boot, e.g., with a scheduled task, is deferred.
  Sessions need a POSIX terminal, so Windows Operators don't offer them
  yet; they do everything else, and run the pipeline without a terminal,
  returning its output.

Starting cloud VMs from the hub is out of scope.

On HPC, where login nodes kill long-lived processes, two modes are
supported:

- `calkit operator start` in the foreground, e.g., inside tmux.
- `calkit operator install --cron`, which checks in with the hub on a
  schedule, reporting scheduler job states, and opens the websocket only
  when there is work to do, e.g., the user has opened a shell.
  Its crontab includes an `@reboot` entry so it checks in at boot.

`scrontab` and similar are deferred.
Heavy work on HPC belongs in scheduler jobs, not on the login node.

In cron mode, the Operator stays running while any session is open, since
sessions end when it exits.
Sessions on login nodes are still subject to the site's limits, as they
are with SSH and tmux, so long-running agents may be better placed on a
compute node or a VM.

### Scheduler jobs

The Operator exposes the existing `calkit scheduler queue`, `logs`, and
`cancel` behavior as structured commands, and reports job states,
including failures and timeouts, in its check-ins.
The hub shows all of a project's jobs on a machine together, labeled by
the workspace that submitted them, since `calkit scheduler queue` only
tracks one checkout's jobs.
It can rerun a failed stage through the Operator.

### CLI

- `calkit operator install [--ssh HOST] [--cron]` installs Calkit on the
  target if needed, then the Operator, then registers it.
  `calkit install operator` does the same, since the Operator is also
  something Calkit installs on a machine, like its native dependencies.
- `calkit operator start|stop|restart|status|logs|uninstall|add-workspace`
  manage the local Operator.
- `calkit hub get operators` lists a user's Operators from the hub.

### Removal

`calkit operator uninstall` removes the service and local state.
Deleting an Operator on the hub revokes its token and, if connected, tells
it to shut down.
A revoked Operator stops itself the next time it fails to connect.
The hub cannot uninstall anything from a machine that is offline.

### Configuration ownership

Operators belong to users and machines, not projects, so they are not
declared in `calkit.yaml`, and project environments don't name them:
Operator names are per user, so a collaborator's Operator on the same
cluster has a different one.
Environments keep naming a `host`, which means the same thing to everyone.

Each Operator registers the hosts it serves, defaulting to its own
hostname, with aliases allowed, e.g., a cluster's login address.
When a stage's environment names a host (phase 3), Calkit asks the hub
whether the user has a live Operator serving it.
If so, the stage runs through the relay, reusing the existing snapshot,
DVC transfer, and locking logic; if not, it falls back to SSH.
This avoids SSH keys, port forwarding, and repeated 2FA prompts on
clusters without changing the project or breaking it for collaborators
without an Operator.

Operators are the first kind of compute users plug into the hub, and not
the last.
Job services, e.g., Hugging Face Jobs (#1748), have no machine of the
user's to run an Operator on, so they're environment kinds, and the hub
can broker them the way it brokers storage: the user adds and names
compute there and enables projects to use it, and a hub environment
names it, optionally locking its properties so a change on the hub
shows up in the project (#1749).
The compute page can list Operators and brokered compute together.

### LaTeX builds

The hub's LaTeX editor compiles a preview in the browser with a WASM TeX
engine, which lacks the stage's real environment and some packages and
fonts, so the hub labels its output unofficial.
The goal is official builds from the hub: saving commits the source,
builds the PDF with the stage's own environment, pushes it to the
project's storage, and commits the updated `dvc.lock`, leaving the stage
up to date.
The editor can instead build on one of the user's Operators, chosen from
a "build on" menu that defaults to the browser.

The Operator builds in a managed workspace for the project, reset for
every build:
it checks out the commit the editor loaded, with `--force`, writes the
editor's unsaved files over it, and runs only the LaTeX stage, like
`calkit run --single-item`.
The stage's other inputs, e.g., figures, come from the DVC cache or remote
rather than being recomputed, and nothing is committed.
The workspace is reused rather than created per build, so its
environment, DVC cache, and Git objects stay warm, but nothing from one
build carries into the next.
One build runs per workspace at a time, and a newer request replaces a
queued one.

A preview build stops there.
A save does the same in the managed workspace, then commits the source
and `dvc.lock`, pushes the PDF with DVC, and pushes the commit.
If the branch moved since the editor loaded it, the Operator merges and
rebuilds rather than overwriting, and reports conflicts back to the
editor.

The build log streams over the relay.
The PDF does not, since it's bulk data:
the Operator uploads it to object storage with a presigned URL from the
API, where it expires after a day, and the editor loads it from there.

To fetch the commit, the Operator uses a personal workspace of the same
project on that machine if there is one, and otherwise the machine's own
Git credentials, which it has because it runs as the user.
Machines with no access to the repository are out of scope for now.

### Loops (future)

Projects will be able to declare loops in `calkit.yaml` under `loops`:
long-running processes that live alongside the pipeline, which runs to
completion, e.g., data collection that appends to one of the project's
datasets on the hub.
The ops sketched in #90 and `calkit/ops.py` are the starting point.
An Operator runs the loops assigned to it in a managed workspace checked
out at the project's default branch, restarting them if they exit and
updating them when the branch moves, so merging to it deploys loops to a
fleet of devices.

Assignment follows the same rule as environments: a project says what a
loop needs, not whose Operator runs it.
Operators will carry labels, e.g., `daq` or `raspberry-pi`, set when
they're installed, and a loop will name the labels it requires, e.g.,
`runs_on: [daq]`.

Nothing in the current design blocks this, as long as these stay open:

- Operator records gain labels next to the hosts they serve.
- The Operator already owns child processes, its sessions, so a loop
  supervisor is another owner beside them.
- Cron mode's idle exit counts sessions and browsers, and will have to
  count running loops too, or loops will require service mode.
- Loops that push data need to write to a project's storage from the
  machine, but Operator tokens only identify the Operator today.
  They'll need scopes granting write access to the datasets of the
  projects whose loops they run, rather than the user's own login.
- Check-ins will report loop states, which is an additive change to the
  check-in body.

The motivating case is a lab device, e.g., one that actuates experiments
and collects their data.
While it serves one project, its control logic is that project's loop.
Several projects' loops can also run on one Operator, each in its own
managed workspace, e.g., different experiments on the same device, since
an Operator is one per machine and account, not per project.
They'd need exclusive access to hardware they share, like stage locks
per machine.
Once lab infrastructure serves many projects, though, its own setup,
e.g., calibration and scheduling, belongs to none of them, and it would
be a concept of its own that projects reference.
Whether that's in scope for Calkit is undecided, and nothing here
depends on it.

### Detached remote stages

Currently, the machine driving a run must stay up until a remote stage
finishes and its outputs are collected.
With an Operator on the remote machine, a run can instead submit a stage
and return.
The Operator watches the job and, when it finishes, commits and pushes the
results from the managed workspace, and the driving workspace pulls them.
This is the asynchronous part of #185 and changes how runs are recorded,
so it follows the pipeline integration phase.

### Phases

1. Daemon, service install, registration, Operator token, hub compute tab
   with liveness, the local server's features moved onto the relay, and
   persistent shell sessions. Done, along with cron mode, `--ssh`
   install, and two-factor authentication.
2. The file tree and editor, scheduler jobs, and LaTeX preview and
   official builds.
3. Pipeline integration: stages on hosts served by an Operator run through
   the relay, and shared DVC caches and stage locks per machine.
4. Detached remote stages.
5. Sharing: collaborator workspaces and multiplayer.
   Operators stay owner-only until how others may use one is decided;
   anything run for someone else would be sandboxed, e.g., in a
   container with only their workspace mounted.
   A shared machine gives each user their own Operator, through
   JupyterHub where it has one (#1744), rather
   than one Operator running as root.
6. Later: native SSH through the relay, e.g., with
   `calkit operator proxy` as an SSH `ProxyCommand`, with the relay
   carrying encrypted bytes to the machine's `sshd` or one built into the
   Operator.
   It would authenticate with the user's own keys, so neither the hub nor
   the relay could get in that way, and it would let VS Code Remote-SSH
   reach the machine without a VPN.
   A setting could then turn off web sessions, leaving an Operator
   reachable only that way and for things like LaTeX builds.
   Upgrading Calkit and restarting an Operator from the hub,
   loops and fleet rollouts (#90), parallel `group` stages (#185),
   a startup command for sessions, agent notifications, and an ACP chat
   view.

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
- **Launching agents directly as sessions.** Saves typing a command, but
  skips the user's shell startup files, so agents may not be found, and
  the session ends when the agent exits.
- **Sessions in tmux.** Would survive Operator restarts but adds a
  dependency and excludes Windows.
- **SSH for web sessions, with keys the hub puts on the machine**, as
  Google Cloud does for its VMs. The hub would still hold or serve
  everything needed to get in, so it's the same trust as the relay
  protocol, and it needs an SSH server, which is off by default on macOS
  and Windows, and loses sessions that outlive their connection.
- **An SSH client in the browser**, e.g., compiled to WebAssembly, with
  keys that never leave it. It would keep the relay out of sessions, which
  signed grants already do more cheaply and for workspace actions too,
  while the hub would still serve the code that uses the keys.
  SSH-over-websocket tools, e.g., wetty and webssh2, end the SSH
  connection on a server, which would then see everything typed.
- **Live file sync between workspaces.** Would make workspaces feel like
  one, but conflicts with agents and concurrent runs would be silent and
  unrecoverable, where Git makes them explicit.
- **Name an Operator in project environments.** Operator names are per
  user, so the project would only work for its author.
- **Declare Operators in `calkit.yaml`, as sketched in #90.** Ties a
  machine to a project; projects should name what they need and users
  should supply machines.
