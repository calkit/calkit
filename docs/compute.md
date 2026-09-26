# Adding compute resources

Some projects contain computationally expensive steps.
One way to manage this is to clone the project onto an [HPC cluster](hpc.md)
and run the pipeline there, commit, and push results back out.
However, this will typically require SSHing into the cluster,
which can feel fragmented if some work is happening there versus
your laptop, for example.

Calkit can also run individual stages on another machine over SSH,
by giving a `system`, `slurm`, or `pbs` environment a `host`
(see [environments](environments.md)).
This works well for sending heavy stages somewhere else,
but it needs SSH access from wherever you run the pipeline,
and it doesn't give you a way to look in on that machine from the web.

Another approach is to install what's called a Calkit Operator
on each machine on which you want to work on at least some part of a Calkit
project.
The Operator manages _workspaces_, both ephemeral and long-lived,
which can be accessed from the CLI and Hub,
for running pipeline stages, viewing status on the web,
and interacting with AI coding agents.

To install the Operator on a given machine, first
[install Calkit](installation.md),
then call:

```sh
calkit install operator
```

This installs the Operator as a service that starts when the machine
boots, so it's running even if you're not logged in.
For example, if you install it on a cloud VM that you stop when you're not
using it, the Operator will be back up as soon as you start the VM again.
Starting at boot may require admin rights;
if you don't have them, the Operator will start when you log in instead,
and the install command will tell you what to run to change that.

If you're running on an HPC, where long-running processes on login nodes
are typically killed, you have two options.
The first is to install it in cron mode with the `--cron` option,
which means it will periodically check in with the Calkit Hub,
reporting the status of any scheduler jobs,
and open up a websocket connection for accepting commands only when
there's something to do.
The second is to run it in the foreground, e.g., inside tmux, with:

```sh
calkit operator start
```

When installed, the Operator registers itself with the Hub and receives
its own token,
which can be revoked without affecting any of your other tokens.
Anyone who can use the Operator from the Hub can open a shell on that
machine as you,
so it's important you only install it on a user account that only you
control.
For the same reason, you'll need two-factor authentication or a passkey
set up on your Hub account before you can open sessions on an Operator.

<!-- prettier-ignore -->
!!! warning
    The Operator gives you access to a machine from outside without a VPN
    or SSH, similar to a VS Code tunnel.
    Some institutions and HPC centers prohibit tools like this,
    so check their policies before installing it.

It's also possible to install the Operator remotely via SSH with

```sh
calkit install operator --ssh
```

The `--ssh` flag accepts a host address, but if this is not provided,
you will be prompted for which of your current machine's known hosts
you'd like to use.
This command will install Calkit on that machine if necessary,
then the Operator, then authenticate with the Hub.

On the Hub, if you go to your settings, you'll see a "compute"
tab that lists your installed Operators and their status.
You can revoke them from there if desired.

By default, the Operator will detect long-lived personal workspaces
in your `~/calkit` folder.
Projects cloned elsewhere can be added with:

```sh
calkit operator add-workspace path/to/project
```

The Operator will only give the Hub access to these workspaces,
plus the ones Calkit creates for running stages on that machine,
and only to you.
When viewing a project on the Hub,
if there is a workspace connected to a live Operator, you'll see
a green dot next to the compute link in the sidebar.

The compute page replaces the project's "local machine" page,
and the Operator replaces `calkit local-server`.

On the project's compute page,
you'll see the project's workspaces on all of your Operators in a table,
e.g., a clone on your laptop and another on a cluster,
along with which commit each is on,
whether it has uncommitted changes,
how far ahead of or behind the Hub it is,
and any live shell sessions in it.
You can enter into a running shell session or start a new one.
Each session starts as a shell in the workspace, with the same environment
you'd get logging in over SSH,
from which you can run any coding agent you like.
For example, you may want two stacked vertically,
with the top one running a coding agent like OpenCode
and the bottom a normal shell session.
Sessions are labeled by what's running in them, e.g., `opencode`.
You'll also be able to see the current pipeline status,
similar to the VS Code extension's stage list.
In fact, the workspace view is similar to working in VS Code,
except greatly simplified.
You can open and edit files as well.
Saving a file writes it in the workspace, just like saving in a local
editor, and committing and pushing are separate steps.
If a coding agent changes a file you have open,
it will reload if you haven't edited it,
and you'll be asked before saving over the agent's changes if you have.

Shell sessions keep running when you close the browser tab.
For example, you can install the Operator on your office workstation,
leave a coding agent running in a workspace there,
then check in on it and interact with it from home, or from anywhere
you can reach the Hub.

When in a workspace view,
you can toggle between that and the Hub for the current project state.
For example,
if you've added a new figure in a workspace and that is currently
activated,
you can see it on the project's figures page and optionally
save the project to push it to the hub and bring the two
into alignment with each other.

## Monitoring cluster jobs

If an Operator is running on a cluster, a workspace's compute page shows
its scheduler jobs, the same ones listed by
[`calkit scheduler queue`](hpc.md#monitoring),
along with their logs.
If a stage's job fails or times out, you'll see it there,
and you can rerun the stage from the Hub without logging in to the
cluster.

## Removal

You can see all Operators attached to your user account with:

```sh
calkit hub get operators
```

Operators can be revoked from the compute tab in your Hub settings.
This revokes the Operator's token and,
if it's connected, shuts it down.

To uninstall the Operator from a machine, run the following on that
machine:

```sh
calkit operator uninstall
```

## Features coming soon

- The ability to share a workspace with a collaborator for "multiplayer" mode.
  Each can see what the other is looking at, chat in real time,
  and make joint commits.
- The ability to allow a collaborator to create their own workspace on a
  given machine, so they don't need to set up Calkit on their own.
- The ability to plug the Hub's LaTeX editor into an Operator for compilation
  and saving in the actual environment attached to its pipeline stage.
- Similar as above, but for figure editing.
- Running pipeline stages on a machine with an Operator without needing
  SSH access to it, using the same `host` in the stage's environment.
- Running stages on another machine without keeping your own machine on
  until they finish, e.g., submitting a long GPU job from your laptop,
  closing it, and pulling the results later.

TODO: Add links to GitHub issues for these and recommend upvoting.
