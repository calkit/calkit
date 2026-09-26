# Adding compute resources

Some projects contain computationally expensive steps.
One way to manage this is to clone the project onto an [HPC cluster](hpc.md)
and run the pipeline there, commit, and push results back out.
However, this will typically require SSHing into the cluster,
which can feel fragmented if some work is happening there versus
your laptop, for example.

TODO: Can Calkit currently run some stages on remote system or cluster envs
via SSH?

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

If you're running on an HPC, you will probably need to install it in
cron mode with the `--cron` option,
which means it will periodically reach out to the Calkit Hub
to see if it should open up a websocket connection for accepting commands.

The Operator will authenticate as you with the Hub,
so it's important you only install it on a user account that only you
control.

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
You can disconnect them from there if desired.

By default, the Operator will detect long-lived personal workspaces
in your `~/calkit` folder.
When viewing a project on the Hub,
if there is a workspace connected to a live Operator, you'll see
a green dot next to the compute link in the sidebar.

TODO: compute replaces the "local machine" link. Operator replaces that
functionality in both the CLI and the hub.

On the project's compute page,
you'll see the list of running workspaces in a table along with
any live shell sessions in them.
You can enter into a running shell session or start a new one.
For example, you may want two stacked vertically,
with the top one running a coding agent like OpenCode
and the bottom a normal shell session.
You'll also be able to see the current pipeline status,
similar to the VS Code extension's stage list.
In fact, the workspace view is similar to working in VS Code,
except greatly simplified.
You can open and edit files as well.

When in a workspace view,
you can toggle between that and the Hub for the current project state.
For example,
if you've added a new figure in a workspace and that is currently
activated,
you can see if on the project's figures page and optionally
save the project to push it to the hub and bring the two
into alignment with each other.

## Features coming soon

- The ability to share a workspace with a collaborator for "multiplayer" mode.
  Each can see what the other is looking at, chat in real time,
  and make joint commits.
- The ability to allow a collaborator to create their own workspace on a
  given machine, so they don't need to set up Calkit on their own.
- The ability to plug the Hub's LaTeX editor into an Operator for compilation
  and saving in the actual environment attached to its pipeline stage.
- Similar as above, but for figure editing.

TODO: Add links to GitHub issues for these and recommend upvoting.
