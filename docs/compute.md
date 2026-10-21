# Adding compute resources

Some projects have steps that need more than a laptop,
or work that happens on several machines,
e.g., a workstation at the office and a cluster.
Calkit can already send individual stages to another machine over SSH,
by giving a `system`, `slurm`, or `pbs` environment a `host`
(see [environments](environments.md)),
or you can clone the project onto an [HPC cluster](hpc.md) and work there.
Both mean logging in to that machine to see what's going on.

Linking your machines to the Calkit Hub lets you work on them from the Hub
instead.
Link each machine you want to work on,
and the Hub's Workspaces pages show your projects there, called
_workspaces_,
with their status, terminal sessions, coding agents, and pipeline runs.

<!-- prettier-ignore -->
!!! warning
    Linking a machine gives you access to it from outside without a VPN
    or SSH, similar to a VS Code tunnel.
    Some institutions and HPC centers prohibit tools like this,
    so check their policies before linking one.

## Linking a machine

First [install Calkit](installation.md), then run:

```sh
calkit hub link install
```

Calkit's [install script](installation.md) can also link the machine
along with installing Calkit with its `--link` option.

The link runs as a service that starts when the machine boots,
so it's running even if you're not logged in.
For example, if you link a cloud VM that you stop when you're not
using it, the link is back up as soon as you start the VM again.
On macOS, starting at boot asks for your password,
and on Linux, linking lets your user's services keep running after you
log out.
If that isn't possible, the link starts when you log in instead,
and `calkit hub link install` says so.
To start it at login on purpose, pass `--login`.
On Windows, it always starts at login.

### On a cluster

Login nodes on most clusters stop long-running processes,
so there you have two options.
The first is to link in cron mode with `--cron`.
It then checks in with the Hub every 5 minutes,
and only connects when you wake it from the Hub,
stopping again after 15 minutes with nothing to do.
The second is to run it yourself, e.g., inside tmux, with:

```sh
calkit hub link start
```

### On another machine

You can also link another machine over SSH:

```sh
calkit hub link install --ssh user@cluster.example.edu
```

The host can be anything you'd pass to `ssh`,
including a host from your `~/.ssh/config`.
This installs Calkit there if needed, then the link,
registering it with the Hub from the machine you're on,
so you don't need to log in to the Hub on the other one.
It can be combined with `--cron`,
or with `--no-service` to only register it there.

### For another hub

To link to a hub other than your default one,
e.g., one run by your institution, pass its URL with `--hub`:

```sh
calkit hub link install --hub https://hub.example.edu
```

A machine can have a link to each hub you use,
and the other `calkit hub link` commands take `--hub` to choose one.
A project folder can be used from one hub at a time:
while one hub has a session open in it or is changing it,
the others show it as in use.

## Keeping it secure

The link gets its own token from the Hub,
which can be revoked without affecting your other tokens.
Only you can see or use your machines,
but anyone signed in to the Hub as you could open a shell on the machine
as you,
so only run it on a user account that only you control.

For the same reason,
connecting to a workspace requires two-factor authentication.
Set it up with an authenticator app under the Machines tab in your Hub
settings.
You'll be asked for a code from the app every 12 hours.

## Finding your workspaces

The link finds the Calkit projects in your `~/calkit` and `~/dev`
folders.
To add one from somewhere else, run on that machine:

```sh
calkit hub link add-workspace path/to/project
```

The Hub can only reach these workspaces,
plus the ones Calkit creates on that machine to run stages.

The Workspaces link at the top of the Hub lists all of them,
grouped by machine and then project,
along with their terminal sessions and coding agents.
You can filter them, e.g., to the ones with uncommitted changes or a
pipeline running.

Each project also has a Workspaces page in its sidebar,
listing that project's workspaces on all of your machines,
e.g., a clone on your laptop and another on a cluster,
with the branch and commit each is on.
The sidebar's Workspaces icon turns green when one of them is on a machine
that's online.

### Creating a workspace

If a linked machine doesn't have the project yet,
the project's Workspaces page has a Create workspace button for it.
The workspace goes in `~/calkit/<project name>` unless you choose
another folder.
Before creating it, the Hub checks that machine:

- If Git doesn't have your name and email there, it asks for them,
  filled in from your Hub profile.
- If the machine can't reach the project's repository over SSH,
  click "Set up SSH".
  The Hub shows the machine's SSH key, making one if it has none.
  Add it to your account's SSH keys on the Git host, e.g., GitHub,
  then click "Check again".
- If Calkit on that machine isn't signed in to the Hub,
  leave "Authenticate this machine with the Calkit CLI" checked,
  so the workspace can pull and push data.

## Working in a workspace

Click a workspace to see its details:

- **Sync:** what there is to pull or push, for both code and data,
  with Pull and Push buttons.
  If the remote has changed too, you'll be offered a merge.
- **Changes:** files that have changed since the last commit,
  with Commit and Discard buttons.
  Discarding keeps a copy of your changes,
  which `calkit stash pop` brings back.
- **Pipeline:** which stages are out of date and why,
  which are running, and the questions they answer.
  Run the whole pipeline or a single stage, and add a new stage.
  You can also run a project's pipeline on one of your machines from the
  project's Pipeline page.
- **Environments:** when each was last checked and whether it has
  changed since.
- **Run log:** the output of the latest run, with a button to stop it.

The "+ Workspace" button creates another workspace for the project on a
new branch, so you can work on a change without disturbing this one.
It shares the same data, so nothing needs pulling again.

### Sessions and coding agents

From a workspace you can open terminal sessions,
each a shell in the workspace with the same environment you'd get
logging in over SSH.
Run any coding agent you like in one,
e.g., Claude Code in one session and a plain shell below it.
Sessions are labeled by what's running in them, e.g., `claude`.

Sessions keep running when you close the browser tab.
For example, you can leave a coding agent running on your office
workstation, then check in on it from home,
or from anywhere you can reach the Hub.

The Hub also finds Claude Code, Codex, and OpenCode
running in a workspace outside of a session,
e.g., in your editor's terminal or in tmux,
and shows what Claude Code and Codex are doing from their own logs.
You can attach to an agent running in tmux.

On Windows, the link can do everything except open terminal sessions,
which aren't supported there yet.

## Managing machines

On a machine, manage its link with:

```sh
calkit hub link status
calkit hub link stop
calkit hub link restart
calkit hub link logs
```

Without `--hub`, `status`, `stop`, and `restart` act on all of the
machine's links.

The Machines tab in your Hub settings lists your machines and their
status, where you can restart or revoke them.
A machine in cron mode shows as asleep until you wake it from the
Workspaces page.
After Calkit is upgraded on a machine,
its link restarts with the new version on its own
once no session or run is using it.

## Removal

Revoking a machine from the Machines tab in your Hub settings
revokes its token and shuts its link down at its next check-in.
To unlink a machine, run this on that machine:

```sh
calkit hub link uninstall
```

## Features coming soon

- Sharing a workspace with a collaborator for "multiplayer" mode,
  where each can see what the other is looking at, chat in real time,
  and make joint commits,
  or letting a collaborator create their own workspace on a machine,
  so they don't need to set up Calkit themselves
  ([#1482](https://github.com/calkit/calkit/issues/1482)).
- Opening and editing a workspace's files from the Hub,
  and switching the project's pages between the Hub's version and a
  workspace's
  ([#1702](https://github.com/calkit/calkit/issues/1702)).
- Seeing a cluster's scheduler jobs for a workspace, with their logs,
  and rerunning a stage whose job failed.
- Plugging the Hub's LaTeX and figure editors into a linked machine,
  to build in the stage's own environment
  ([#1111](https://github.com/calkit/calkit/issues/1111)).
- Running stages on a linked machine without SSH access to it,
  and without keeping your own machine on until they finish,
  e.g., submitting a long GPU job from your laptop, closing it,
  and pulling the results later
  ([#185](https://github.com/calkit/calkit/issues/185)).
- Upgrading Calkit on a linked machine from the Hub
  ([#1870](https://github.com/calkit/calkit/issues/1870)).

If one of these would help you, add a 👍 to its issue.
