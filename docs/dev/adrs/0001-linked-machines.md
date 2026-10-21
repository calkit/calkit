# ADR 0001: Linked machines

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
Linked machines should instead show one project and all of its parts in one
place: its workspaces, a shell, and sessions of whichever coding agents
the user runs.

Two concrete use cases drive the MVP:

- An HPC user wants to see their jobs in the queue, read their logs, and
  notice when a stage times out so they can rerun it, without logging in
  to the cluster.
- A user wants to link an office workstation to the hub and, from
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
A link is a long-running Calkit process, one per machine and user
account, that manages workspaces on that machine and accepts commands from
the hub.
#185 and #90 must remain possible on top of this design but are not built
in it.
#918 is a CI integration and is not called a link.

The link replaces `calkit local-server` and the hub's "local machine"
tab completely.
The local server's endpoints become the link's first set of commands,
and the hub's Workspaces pages replace the tab.

### Transport

The link holds an outbound websocket to the hub, which relays traffic
between browsers and machines.
This works behind NAT and firewalls without opening ports.
There is no direct or localhost path for now, even when the browser is on
the same machine.
SSH environments remain the way to run on other machines without the hub.

Relayed traffic is kept to what is interactive and small:

- Terminal traffic is keystrokes and screen output, typically a few KB/s
  while a session is active and nothing while idle.
  The link coalesces output into frames every few tens of
  milliseconds, which matters for agent TUIs that redraw often.
  The relay doesn't compress frames with permessage-deflate.
- Structured commands, e.g., status, the scheduler queue, a page of logs,
  or a file opened in the editor, return small payloads.
  The relay enforces a maximum message size.
- Bulk data never goes through the relay.
  Outputs travel the way they already do, through Git and DVC to the
  project's storage, and large file downloads use presigned storage URLs.
  Port forwarding, e.g., to Jupyter or a web app, is out of scope.
- Status that only needs to be current to within minutes, e.g., liveness
  and scheduler job states, is reported by periodic HTTP check-ins, not
  held websockets, so an idle link costs the hub almost nothing.

The relay runs as its own single-process async service, not inside the
API's workers.
With the API's multiple workers, a browser and its link would often
land on different ones and have to meet through Valkey pub/sub on every
message.
A single process pairs them in memory and can be deployed, scaled, or
moved independently of the API.
The API issues short-lived tokens the relay verifies to pair a browser
with a machine it's allowed to use.

The relay meters bytes per machine from the start.
The link's command protocol is independent of transport, so if
metering shows the relay costs too much, a direct browser-to-machine path
can be added with the relay handling only signaling, e.g., WebRTC data
channels, falling back to relaying when a peer-to-peer connection can't be
made.

### Authentication and permissions

`calkit hub link install` registers the machine with the hub using the
user's existing token and receives a dedicated machine token, stored
locally.
That token can only connect as that machine, so revoking it does not
affect the user's other tokens.

By default, only the machine's owner can use it, and only inside
allowlisted workspaces:
discovered or registered personal workspaces and managed workspaces.
Within those, the owner can open shells and edit files.
The allowlist and other settings live in
`~/.calkit/hubs/<hub>/link.yaml`.
Sharing with collaborators is out of scope for the MVP.

The link effectively gives the hub a shell on the machine, and
bypassing a VPN is the point, so the hub account becomes the only barrier
in front of those machines.
Opening sessions on a machine therefore requires two-factor
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
  short-lived token in an HttpOnly cookie, not a record on the account.
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
- Changing a verified email takes a code sent to it for the new address,
  and setting up an authenticator app or registering a machine takes a
  verified email, so a stolen session can't move the account to an
  attacker's inbox and
  set up their app.
  A Google sign-in that claims an account whose email was never verified
  resets whatever someone else could have set up on it.
- Code checks lock their row, so parallel guesses can't get past the
  limit.
- The relay signs with a key of its own, since it's exposed to the
  internet, and takes tokens in a message rather than the URL, once each.
- The link doesn't take the relay's word for who opened a channel.
  The API signs a grant for each browser connection, naming the machine
  and its owner, with an Ed25519 key only it holds, and the link
  checks it against the public key the API sends with each check-in, over
  HTTPS, using each grant once, even across restarts.
  So the relay alone can't open channels, for shells or anything else,
  and what's left to trust is the API itself, as with any web terminal
  its pages serve.
- The grant also names a key the browser made for that connection and
  can't export, which signs every message, numbered, so the relay can't
  use a grant it carries or act inside a channel.
  The grant names its sign-in too, and the link closes the channel
  within a check-in once that sign-in ends, e.g., with a password change.
- The link registers with the user's own hub, never one named by a
  project in the working directory, refuses to connect without TLS except
  locally, and always refuses to run as root, since its sessions would be
  root shells.
  Paths and clone URLs from the hub have to be plain ones, so they can't
  be taken as options or reach outside the workspace, and files a repo
  committed as links aren't followed.
- Links built from project data only allow web and email URLs, since a
  `javascript:` URL in a project's `calkit.yaml` would otherwise run in
  the owner's browser, where it could reach their machines.
  Passkeys can be added later as another way to satisfy the same check.
  The user docs must say prominently to run the link only on
  accounts the user alone controls, and to check institutional policy
  first, since this is equivalent to a VS Code tunnel, which some
  institutions and HPC centers prohibit.

A third review closed what was left to the relay and to stolen sessions:

- The link has a key of its own, which the hub keeps the first time
  it's sent and never replaces, and signs every reply with it, bound to
  the channel's grant.
  The browser gets that key from the API, not the relay, and messages are
  numbered contiguously both ways, with a gap closing the channel.
  So the relay can still read both directions, including what's typed in
  a terminal and what it shows, but can't forge, drop, or reorder
  anything in either.
- Channels last only as long as the second factor that let them open,
  and close while the link hasn't checked in for 10 minutes, since it
  can't then tell which sign-ins have ended.
  The relay drops a link's connection whose token isn't refreshed
  after check-ins, so a revoked machine is cut off within 10 minutes.
- The machine's CLI token, which pulling and pushing data use, is issued
  by the hub to the link, which fetches it over HTTPS once its owner
  asks, rather than made in the browser and sent through the relay.
  It's tied to the machine and revoked with it.
  The hub's token is removed from DVC remotes that aren't on the hub
  before pulls and pushes, and files holding it are never saved to a
  commit.
- Signing out ends the session, and other sessions can be ended from
  user settings.
  Revoking a machine takes a signed-in session, and the owner is
  emailed whenever one is registered or revoked.

Shell sessions aren't confined to workspaces.
Only a machine's owner can open them, and the owner already has a shell
on their own machine, so hiding the rest of it would cost usability,
e.g., toolchains, Git credentials, and agent configs in the home
directory, without protecting anything from them.
Confinement is planned for when others can open sessions on someone's
machine, i.e., organization machines and shared workspaces: each user
isolated as a separate OS account or in a container, with filesystem
restrictions on top, i.e., Landlock on Linux and `sandbox-exec` on macOS,
allowing system paths, the workspace, and a configurable list of home
paths, and refusing sessions where they can't be enforced.

#### Credentials in sessions

On macOS the link is a LaunchDaemon by default, so what runs in its
sessions is outside the user's login session and can't reach their login
keychain, where Calkit keeps hub tokens, nor, usually, an SSH agent.
Pulling and pushing there would otherwise start a device login, or fail.
Sessions instead get credentials from their link, which gets them from the
hub over HTTPS when they're asked for, so they never pass through the relay,
aren't in the session's environment, and aren't written to disk.

- Each session asks its link over a Unix socket in a folder only the
  user can open, with a secret only that session is told, which the link
  answers only while the session runs.
  Other users can't reach it, and the user's own processes can already
  reach everything a session can.
- The link shows the hub the grant of the channel that opened the
  session, along with its machine token.
  The hub issues credentials only for a grant it signed for that machine
  and its owner, whose sign-in is still live and whose second factor hasn't
  expired, and not if two-factor authentication was set up again since.
  The relay, which carries grants, has no machine token, and a machine token
  alone has no grant, so neither can get credentials, and what lets a
  session open is what keeps its credentials coming.
  A channel attaching later with a longer-lasting second factor takes over,
  so a long-running agent keeps working while its owner keeps visiting.
- Calkit gets a token for the link's hub only, lasting 15 minutes, and at
  most until that second factor expires, which the link gets again as it
  runs out.
  It stops working once the machine is revoked or the sign-in ends, and
  can't make personal access tokens, which would outlive it.
  A raw token in the environment, e.g., `CALKIT_TOKEN`, would be sent to
  whichever hub a command uses, which is why the link checks the hub asked
  for is its own.
- Git gets the owner's GitHub token, which the hub already keeps and
  refreshes, through a credential helper the session's environment
  configures for `https://github.com` only, after any of the user's own.
  SSH remotes aren't rewritten to HTTPS, since keys without a passphrase
  work at boot and keys with one can be typed for in a session, while the
  hub's GitHub token only reaches repositories its GitHub App can.
- HTTP DVC remotes keep a token in `.dvc/config.local`, which sessions
  neither make nor write, so only ones set up beforehand work there;
  `ck://` remotes, the default, get the session's token as they go.

### Workspaces

There are two kinds:

- Personal workspaces are ordinary long-lived checkouts.
  The link discovers Calkit projects on its hub under `~/calkit` and
  `~/dev`, i.e., ones whose declared `hub`, or else the user's default
  hub, is the link's, so a hub never learns of projects on others.
  `calkit hub link add-workspace <path>` registers ones elsewhere, or on
  another hub.
  These are the only kind edited from the hub.
- Managed workspaces are the existing hidden ones under
  `~/.calkit/workspaces`, checked out with `--force` and used for running
  stages.
  They are shown in the hub but not edited there.

A machine can have a link for each hub it's connected to, e.g., the
public hub, an institution's, and one running locally for development,
each with its own config, service, lock, and log, named by the hub's key,
e.g., `calkit.io`, which is also how managed workspaces are filed.
`--hub` picks which one a command acts on, and without it,
`calkit hub link install` uses the user's default hub and other commands
the only one linked.
A workspace can be seen by more than one of them, e.g., one added to
another hub with `add-workspace`, but is used by one at a time: a link takes a lock in
the workspace itself, `.calkit/local/hub-link.lock`, while a session or
an action that changes it is running, and the others refuse to change it
and report it as in use from another hub, without saying which, until
it's released.
A lock left by a link that's no longer running is stale and can be
taken.

The hub presents itself as a workspace too: the default one, and the
project's source of truth, which can be viewed and edited but runs
nothing.
A "view from" select in the project's menu switches between the hub, its
change batches (#445), which extends the existing `ref` picker, and the
user's machines' workspaces, read live through their links, so only
while they're online and with the second factor sessions take.
What's in the view is always relative to the hub, and the key design
point is showing how far each change has gone, in plain words rather
than Git's:

- Changed on a machine, i.e., uncommitted: "only on office-laptop,
  unsaved".
- Saved on a machine, i.e., committed but not pushed: "saved on
  office-laptop, not shared".
- In a change batch, i.e., pushed to its branch: "in batch: Revise
  figure 3".
- In the project, i.e., merged into `main`, which is the default and needs
  no label.

A bar says which workspace is in view and what it holds beyond the hub,
anything that differs from the hub carries its label and can be
compared with the hub's version side by side, and each state offers the
next step: save, share, and add to the project.
DVC outputs follow the same states, e.g., a figure produced on a machine
but not yet pushed to storage.
The hub's check-in badges use the same words, e.g., "1 not shared"
rather than "1 ahead".

A workspace on `main` can sync with the hub automatically, pushing what's
saved and pulling what's new, so for work straight on the project the
saved and shared states collapse into one, while change batches keep an
explicit step before anything reaches `main`.
It's opt-in per workspace, since it pushes without asking, and stops at
anything that needs a person, e.g., a merge conflict, which the hub then
shows on that workspace.

What's in view decides where edits go.
Viewing the hub or a batch, edits are saved to it as commits, and builds
run in a managed workspace on a machine, as in [editor
builds](#editor-builds), leaving the user's own checkout alone.
Viewing a machine's workspace, edits land in that checkout, unsaved, as
if the user were at the machine, and runs happen there, which is how to
continue a session at the office from home.

### Workspace status

Check-ins carry only what's cheap to get for every workspace every minute:
branch, commit, whether there are uncommitted changes, how far it is from
its remote, and the pipeline's run state.
That's whether a live process holds DVC's lock, which stages are running
and since when, from the run's log, and how the latest run ended, from
the record `calkit run` leaves.
The hub shows these without connecting to the machine or asking for a
second factor, so someone who only wants to know whether a run is going
or failed doesn't need a session.
The full status, i.e., stale stages and why, running stages, and changed
files and data, comes from `calkit status --json`, the same source as the
VS Code extension's sidebar.
It's too expensive to compute continuously, so the link runs it when
someone opens the workspace in the hub, which then follows it while a run
is in progress.

### Multiple workspaces per project

A project can have many workspaces across a user's machines, e.g., a
laptop checkout, a personal checkout on a cluster, and a managed workspace
on the same cluster.

Git and DVC remain the only way state moves between workspaces.
There is no live file sync between them.
Each pipeline run has a single workspace driving it, and its results
reach the others through commits, pushes, pulls, and DVC.
This is how the laptop and managed workspaces already interact, and it is
the only model that stays predictable with an agent editing in one
workspace while stages run from another.
The hub makes divergence visible instead of hiding it: its Workspaces page
lists every workspace of the project with its commit, whether it has
uncommitted changes, and how far ahead of or behind the hub it is, plus the
sessions running in it.

To avoid paying twice for expensive stages, the link points all of a
project's workspaces on one machine at a shared DVC cache, so the run cache
lets one workspace restore outputs another has already computed instead of
recomputing them.
A lock keyed on the stage and its input hashes, held while a stage runs on
that machine, makes a second request for the same computation wait for the
first instead of submitting its own job.

### Sessions and the workspace view

The link owns its PTYs, so shell sessions, and any coding agent
running in one, survive browser disconnects.
Sessions end when closed explicitly or when the link restarts.
Windows machines don't offer sessions yet.

Every session is a login shell in the workspace, so it has the user's
full environment, e.g., `PATH` additions and modules, as with SSH.
Users run whichever coding agent they like from it, and get the shell back
when the agent exits.
The hub labels each session by its terminal's foreground process, e.g.,
`claude` or `bash`.
Agent-specific features are deferred:

- An optional command to run when a session starts.

- Notifications when an agent is waiting for input, detected from the
  terminal bell or OSC 9/777 escape sequences in its output.
- A chat view of a session, better suited to phones than a terminal, via
  the Agent Client Protocol (ACP), which several agents support natively
  or through adapters.
  This is the one feature that needs the link to launch the agent
  itself, in ACP mode rather than as a TUI.
  Terminals remain the baseline, since they work with every agent.

The hub's workspace view is built natively: xterm.js terminals over the
relay, the pipeline stage list, and a file tree with a simple editor.
We don't embed a full editor such as openvscode-server.

The editor works on the workspace's files directly through the link,
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

`calkit hub link install` installs a service that runs as the user and,
where allowed, starts at boot rather than at login.
This covers machines nobody logs in to, e.g., a cloud VM that is stopped
when not in use: when it starts again, so does the link.
Because the link only connects outbound, and its token and the
machine ID live on disk, a new IP address after a restart doesn't matter.
While a machine is off, the hub shows the machine as offline with when it
was last seen.

- Linux: a `systemd --user` service with lingering enabled, so the user's
  services start at boot and survive logout.
  Installing enables lingering when permitted, or with sudo if it can
  ask; otherwise it warns and prints the `sudo loginctl enable-linger`
  command.
- macOS: a LaunchDaemon with `UserName` set to the user when they have
  admin rights, otherwise a LaunchAgent that starts at login, with a
  warning.
- With `--login`, it starts at login on Linux and macOS too, without
  asking for sudo.
- Windows: a script in the user's Startup folder that starts it hidden at
  login, which needs no admin rights.
  Starting at boot, e.g., with a scheduled task, is deferred.
  Sessions need a POSIX terminal, so Windows machines don't offer them
  yet; they do everything else, and run the pipeline without a terminal,
  returning its output.

Starting cloud VMs from the hub is out of scope.

On HPC, where login nodes kill long-lived processes, two modes are
supported:

- `calkit hub link start` in the foreground, e.g., inside tmux.
- `calkit hub link install --cron`, which checks in with the hub on a
  schedule, reporting scheduler job states, and opens the websocket only
  when there is work to do, e.g., the user has opened a shell.
  Its crontab includes an `@reboot` entry so it checks in at boot.

`scrontab` and similar are deferred.
Heavy work on HPC belongs in scheduler jobs, not on the login node.

In cron mode, the link stays running while any session is open, since
sessions end when it exits.
Sessions on login nodes are still subject to the site's limits, as they
are with SSH and tmux, so long-running agents may be better placed on a
compute node or a VM.

### Scheduler jobs

The link exposes the existing `calkit scheduler queue`, `logs`, and
`cancel` behavior as structured commands, and reports job states,
including failures and timeouts, in its check-ins.
The hub shows all of a project's jobs on a machine together, labeled by
the workspace that submitted them, since `calkit scheduler queue` only
tracks one checkout's jobs.
It can rerun a failed stage through the link.

### CLI

- `calkit hub link install [--ssh HOST] [--cron]` installs Calkit on the
  target if needed, then the link, then registers it.
- `calkit hub link start|stop|restart|status|logs|add-workspace` manage
  the local link, and `calkit hub link uninstall` removes it.
- `calkit hub get machines` lists a user's machines from the hub.

### Removal

`calkit hub link uninstall` revokes the machine on the hub with its own
token and removes the service and local state.
Deleting a machine on the hub revokes its token and the CLI token
issued to it, and its sessions' tokens stop working.
The link stops at its next check-in, when the hub refuses its token,
and the relay drops its connection within 10 minutes, once it can no
longer refresh its relay token.
The hub cannot uninstall anything from a machine that is offline.

### Configuration ownership

Links belong to users and machines, not projects, so they are not
declared in `calkit.yaml`, and project environments don't name them:
Machine names are per user, so a collaborator's link on the same
cluster has a different one.
Environments keep naming a `host`, which means the same thing to everyone.

Each machine registers the hosts it serves, defaulting to its own
hostname, with aliases allowed, e.g., a cluster's login address.
When a stage's environment names a host (phase 3), Calkit asks the hub
whether the user has a live link serving it.
If so, the stage runs through the relay, reusing the existing snapshot,
DVC transfer, and locking logic; if not, it falls back to SSH.
This avoids SSH keys, port forwarding, and repeated 2FA prompts on
clusters without changing the project or breaking it for collaborators
without a linked machine.

Linked machines are the first kind of compute users plug into the hub, and not
the last.
Job services, e.g., Hugging Face Jobs (#1748), have no machine of the
user's to link, so they're environment kinds, and the hub
can broker them the way it brokers storage: the user adds and names
compute there and enables projects to use it, and a hub environment
names it, optionally locking its properties so a change on the hub
shows up in the project (#1749).
The hub calls these pages Workspaces.
"Compute" is saved for brokered compute,
and pipeline runs from elsewhere, e.g., GitHub Actions,
go on the pipeline page, since they aren't interactive like workspaces.

### Editor builds

The most important thing linked machines enable is plugging in a machine to do
the work behind the hub's editors: edit a figure or a paper on the hub,
and have the machine produce the real result, with its own environment,
before and after saving.
Seeing where the pipeline is running and rerunning it on a chosen machine
come next, and sessions are for advanced users.

The hub's figure editor previews with Pyodide and its LaTeX editor with a
WASM TeX engine, both in the browser, which lack the stage's real
environment, so the hub labels their output unofficial, and saving
commits only the source, leaving the stage stale.
The goal is official builds from the hub: saving commits the source,
builds the output with the stage's own environment, pushes it to the
project's storage, and commits the updated `dvc.lock`, leaving the stage
up to date.
The editor can instead build on one of the user's machines, chosen from
a "build on" menu that defaults to the browser (#1111).

The link builds in a managed workspace for the project, reset for
every build:
it checks out the commit the editor loaded, with `--force`, writes the
editor's unsaved files over it, and runs only the stages the change
affects, e.g., the figure's or the LaTeX stage, like
`calkit run --single-item`.
The stage's other inputs, e.g., figures, come from the DVC cache or remote
rather than being recomputed, and nothing is committed.
The workspace is reused rather than created per build, so its
environment, DVC cache, and Git objects stay warm, but nothing from one
build carries into the next.
One build runs per workspace at a time, and a newer request replaces a
queued one.

A preview build stops there, and the editor shows the result next to the
current one, so the change can be judged before it's kept; discarding it
leaves nothing behind.
A save does the same in the managed workspace, then commits the source
and `dvc.lock`, pushes the output with DVC, and pushes the commit, to
`main` or to a change batch, a simplified branch the save dialog offers
alongside `main` (#445).
If the branch moved since the editor loaded it, the link merges and
rebuilds rather than overwriting, and reports conflicts back to the
editor.

The build log streams over the relay.
The output does not, since it's bulk data:
the link uploads it to object storage with a presigned URL from the
API, where it expires after a day, and the editor loads it from there.
A build runs project code on the machine, so like a session it takes the
grant and second factor the relay requires.

To fetch the commit, the link uses a personal workspace of the same
project on that machine if there is one, and otherwise the machine's own
Git credentials, which it has because it runs as the user.
Machines with no access to the repository are out of scope for now.

### Loops (future)

Projects will be able to declare loops in `calkit.yaml` under `loops`:
long-running processes that live alongside the pipeline, which runs to
completion, e.g., data collection that appends to one of the project's
datasets on the hub.
The ops sketched in #90 and `calkit/ops.py` are the starting point.
A link runs the loops assigned to it in a managed workspace checked
out at the project's default branch, restarting them if they exit and
updating them when the branch moves, so merging to it deploys loops to a
fleet of devices.

Assignment follows the same rule as environments: a project says what a
loop needs, not whose machine runs it.
Machines will carry labels, e.g., `daq` or `raspberry-pi`, set when
they're linked, and a loop will name the labels it requires, e.g.,
`runs_on: [daq]`.

Nothing in the current design blocks this, as long as these stay open:

- Machine records gain labels next to the hosts they serve.
- The link already owns child processes, its sessions, so a loop
  supervisor is another owner beside them.
- Cron mode's idle exit counts sessions and browsers, and will have to
  count running loops too, or loops will require service mode.
- Loops that push data need to write to a project's storage from the
  machine, but machine tokens only identify the machine today.
  They'll need scopes granting write access to the datasets of the
  projects whose loops they run, rather than the user's own login.
- Check-ins will report loop states, which is an additive change to the
  check-in body.

The motivating case is a lab device, e.g., one that actuates experiments
and collects their data.
While it serves one project, its control logic is that project's loop.
Several projects' loops can also run on one machine, each in its own
managed workspace, e.g., different experiments on the same device, since
a link is one per machine and account, not per project.
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
With a link on the remote machine, a run can instead submit a stage
and return.
The link watches the job and, when it finishes, commits and pushes the
results from the managed workspace, and the driving workspace pulls them.
This is the asynchronous part of #185 and changes how runs are recorded,
so it follows the pipeline integration phase.

### Phases

1. Daemon, service install, registration, machine token, hub Workspaces tab
   with liveness, the local server's features moved onto the relay, and
   persistent shell sessions. Done, along with cron mode, `--ssh`
   install, and two-factor authentication.
2. Editor builds for figures and papers, with change batches; where the
   pipeline is running shown on the pipeline view, and rerunning stages
   on a chosen machine; then the file tree and editor, and scheduler
   jobs.
3. Pipeline integration: stages on hosts served by a linked machine run through
   the relay, and shared DVC caches and stage locks per machine.
4. Detached remote stages.
5. Sharing: collaborator workspaces and multiplayer.
   Machines stay owner-only until how others may use one is decided;
   anything run for someone else would be sandboxed, e.g., in a
   container with only their workspace mounted.
   The same goes for donating spare compute to others' projects, e.g.,
   building their LaTeX papers, which also needs results checked, e.g.,
   by running a job on two machines, and is a sharing policy on brokered
   compute (#1749).
   A shared machine gives each user their own link, through
   JupyterHub where it has one (#1744), rather
   than one link running as root.
6. Later: native SSH through the relay, e.g., with
   `calkit hub link proxy` as an SSH `ProxyCommand`, with the relay
   carrying encrypted bytes to the machine's `sshd` or one built into the
   link.
   It would authenticate with the user's own keys, so neither the hub nor
   the relay could get in that way, and it would let VS Code Remote-SSH
   reach the machine without a VPN.
   A setting could then turn off web sessions, leaving a machine
   reachable only that way and for things like LaTeX builds.
   Also keeping the machine awake while a session or run is active, as
   `code tunnel --no-sleep` does, e.g., with `caffeinate` on macOS, so a
   long run isn't lost to sleep, and forwarding a workspace's ports
   through the relay, e.g., to open its Jupyter server from the hub,
   within the relay's traffic budget.
   Upgrading Calkit from the hub,
   loops and fleet rollouts (#90), parallel `group` stages (#185),
   a startup command for sessions, agent notifications, and an ACP chat
   view.

## Consequences

- One hub-connected process now does what `calkit local-server` did, and
  more, so the local server and its hub tab are removed rather than
  maintained in parallel.
- The link requires the hub.
  The hub is still optional for the project itself, which lives in Git,
  and SSH environments still work without it.
- All interactive traffic passes through the relay, which costs latency
  and hub bandwidth.
  Keeping bulk data off the relay and metering it keeps that bounded, and
  a direct path can be added later without changing the link's
  command set.
- The hub gains a new service to deploy and monitor.
- The hub becomes a way to get a shell on users' machines, so the security
  of the hub, of user sessions, and of machine tokens matters more than
  before.
- Personal and managed workspaces follow different rules, which the hub
  must make visible.

## Alternatives considered

- **Keep the local server alongside the link.** Two ways to do the
  same thing from the hub, one of which only works on localhost.
- **Direct or localhost connections from the browser.** Lower latency and
  no relayed traffic, but needs port exposure or WebRTC signaling plus a
  relay fallback anyway; deferred until metering shows it's needed.
- **Relaying inside the API workers.** No new service, but pairs across
  workers through Valkey pub/sub and competes with API requests.
- **Reuse the user's CLI token.** Revoking one machine would revoke
  everything.
- **Zero permissions until approved on the machine.** Safer, but adds
  friction the owner-only allowlist mostly removes.
- **Embed openvscode-server.** Full-featured immediately, but heavy and
  hard to integrate with hub pages.
- **VS Code Remote Tunnels instead of linked machines.** The same idea, an
  outbound connection through a cloud relay from a machine the user owns
  to a browser, and ahead of linked machines as an IDE: a full editor,
  extensions, and port forwarding, with SSH inside the tunnel, so the
  relay can't read sessions. But it knows nothing about projects, so
  pipeline state, runs on a chosen machine, and official outputs from the
  hub's editors aren't possible through it, and it runs through
  Microsoft's relay, with a limit of 10 tunnels per account, a server
  meant for one client at a time, and a process that has to keep
  running, which cluster login nodes often don't allow.
  It can still be used alongside, by running `code tunnel` in a session.
- **Launching agents directly as sessions.** Saves typing a command, but
  skips the user's shell startup files, so agents may not be found, and
  the session ends when the agent exits.
- **Sessions in tmux.** Would survive link restarts but adds a
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
- **Name a machine in project environments.** Machine names are per
  user, so the project would only work for its author.
- **Declare machines in `calkit.yaml`, as sketched in #90.** Ties a
  machine to a project; projects should name what they need and users
  should supply machines.
