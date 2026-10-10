# Operator protocol

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

How Operators, the hub API, the relay, and browsers talk to each other.
The decisions behind it are in [ADR 0001](adrs/0001-operators.md).

## Parties

- The **API** is the hub backend.
  It owns Operator records and issues every token.
- The **relay** is a single-process service that pairs websockets.
  It has no database and trusts only JWTs signed with the API's secret.
- The **Operator** runs on a user's machine.
- The **browser** is the hub frontend.

## Tokens

| Token              | Form                            | Lifetime      | Used for                                    |
| ------------------ | ------------------------------- | ------------- | ------------------------------------------- |
| Operator token     | `cko_` + selector and verifier  | Until revoked | Authenticating the Operator to the API      |
| Operator relay JWT | JWT with scope `relay:operator` | 10 minutes    | Opening the Operator's relay connection     |
| Browser relay JWT  | JWT with scope `relay:browser`  | 60 seconds    | Opening one browser connection to the relay |

Operator tokens are stored like personal access tokens: a selector to look
the record up and a hashed verifier.
Relay tokens are only checked when a connection opens.
Revoking an Operator takes effect at its next check-in, when the API
rejects its token and the Operator shuts down.

## API

- `POST /operators`, with the user's token, registers an Operator and
  returns its ID, name, and Operator token.
  The token is only returned here.
- `GET /operators` lists the user's Operators.
- `DELETE /operators/{operator_id}` revokes one.
- `POST /operators/check-in`, with the Operator token, records that the
  Operator is alive, how it runs (`mode`: `service`, `foreground`, or
  `cron`), whether it's `connected` to the relay, and what workspaces it
  has, each with its Git state and pipeline run state: `running`,
  `running_stages`, `running_since`, and `last_run` (`status`, `started`,
  `ended`, and `failed_stages`), when it was last active
  (`last_activity`), and the coding agents running there (`agents`), and
  whether a restart is pending (`restart_pending`).
  Each agent, e.g., Claude Code, Codex, or opencode, is found by its
  command and working directory, however it was started, and has its
  `tool`, `pid`, when it `started`, `where` it runs (`session`, one of the
  Operator's, `tmux`, or another `terminal`), the `app` it was started
  from, e.g., `Code`, and the `name` and `status` it gives itself, if any.
  It returns the relay URL, an Operator relay token, `connect`, which
  tells an Operator in cron mode whether to connect, and `restart`, which
  passes on a restart its owner asked for.
  Operators check in every 60 seconds while connected.
- `POST /operators/{operator_id}/wake`, with the user's token, asks an
  Operator in cron mode to connect at its next check-in.
  The request lapses after 15 minutes and is cleared once the Operator
  checks in connected.
- `POST /operators/{operator_id}/restart`, with the user's token, asks an
  Operator to restart, which it hears at its next check-in.
- `POST /operators/{operator_id}/relay-token`, with the user's token,
  returns the relay URL and a browser relay token for that Operator.
  It requires an access token from a person signing in to the web app,
  whose sign-in session is still live, not a personal access token or a
  CLI, CI, or GitHub token login, and proof that the session entered a
  two-factor code within the last 12 hours:
  the `second_factor_token` returned by `POST /user/totp/verify` (or
  `/confirm`), sent in an `X-Second-Factor` header.
  That token names the session, so it's worthless to any other, and
  changing the password ends every other session.
  Otherwise it answers 403 with a detail the browser recognizes, to prompt
  for setup or a code.
  Setting up two-factor authentication (`POST /user/totp`) emails a code,
  which confirming takes along with one from the authenticator app.
  It, and registering an Operator, require a verified email, and changing
  a verified email takes a code sent to it.
- `GET /projects/{owner}/{name}/workspaces` lists the project's workspaces
  across the user's Operators, from their latest check-ins.

An Operator is online if its latest check-in was connected and within the
last three minutes, and asleep if it's in cron mode, not online, and has
checked in within the last 15 minutes.
Operators check in with `connected` false as they shut down, so they show
as offline or asleep right away.

## Cron mode

On machines where long-running processes aren't allowed, e.g., a
cluster's login node, cron runs `calkit operator start --mode cron` every
5 minutes and at boot.
It checks in with `connected` false and exits unless `connect` is true.
If it is, it runs as usual until it has had no sessions and no browsers
for 15 minutes.
A lock file keeps one Operator running per machine, user, and hub.

## Restarts

An Operator restarts once nothing is using it, i.e., it has no sessions
and no workspace actions, e.g., runs, in progress, when:

- The Calkit version installed differs from the one it's running, e.g.,
  after an automatic upgrade.
- `calkit upgrade` or `calkit dev upgrade` asks it to, by writing
  `restart` in its directory, which covers a dev install updated without a
  new version.
- Its owner asks on the hub.

It checks every 30 seconds and reports `restart_pending` until it has
restarted.
On Linux and macOS it execs itself, so the process ID the service manager
tracks stays the same; on Windows it starts a new process.
On Windows, a running Operator holds files an upgrade replaces, so an
upgrade instead asks it to stop (writing `stop`), waits for it to exit, and
afterwards starts those installed as a service again, whether or not the
upgrade worked.

## Relay

The relay serves two websocket endpoints.
Each connection sends its token in its first message,
`{"type": "auth", "token": ...}`, rather than the URL, so tokens stay out
of access logs, and is closed with code 4401 if it doesn't within 10
seconds or the token is invalid.
Tokens are signed with `RELAY_SECRET_KEY`, which can't sign logins, and
each opens only one connection.

- `/operator`, one connection per Operator.
  A new connection replaces an existing one for the same Operator.
- `/browser`, any number per Operator.
  Closes with code 4404 if the Operator isn't connected.

When a browser connects, the relay assigns it a channel ID and sends the
Operator `{"type": "channel.open", "ch": ..., "user_id": ..., "grant": ...}`.
The grant, which comes from the browser's relay token, is an EdDSA JWT
the API signed, with the Operator's ID as `aud`, its owner as `sub`, a
`jti`, and a 60 second `exp`.
The Operator checks it against the key it pinned from `grant_public_key`
when it registered (or at its first check-in, if registered before), and
refuses channels without a valid, unused one.
Browser messages are forwarded to the Operator as
`{"type": "channel.message", "ch": ..., "msg": ...}`,
and the Operator sends `{"ch": ..., "msg": ...}` to reach a browser, which
receives `msg` unwrapped.
When a browser disconnects, the Operator gets
`{"type": "channel.close", "ch": ...}`.
When the Operator disconnects, its browsers are closed with code 4410.

All messages are JSON text frames.
Messages over 256 KiB close the connection with code 1009.
The relay counts bytes in each direction per Operator and logs them every
minute.

## Operator messages

These are the `msg` payloads between a browser and an Operator.
Requests carry an `id`, answered by `{"type": "result", "id": ...,
"result": ...}` or `{"type": "error", "id": ..., "error": ...}`.

| Browser sends     | Fields                            | Result             |
| ----------------- | --------------------------------- | ------------------ |
| `workspaces.list` | `id`                              | List of workspaces |
| `sessions.list`   | `id`                              | List of sessions   |
| `sessions.open`   | `id`, `workspace`, `cols`, `rows` | `{"session": ...}` |
| `sessions.attach` | `id`, `session`, `cols`, `rows`   | `{"session": ...}` |
| `sessions.detach` | `session`                         |                    |
| `sessions.input`  | `session`, `data`                 |                    |
| `sessions.resize` | `session`, `cols`, `rows`         |                    |
| `sessions.close`  | `session`                         |                    |

`sessions.open` starts a login shell in a workspace the Operator allows
and attaches the channel to it.
An optional `command` is typed into the shell once it starts, e.g.,
`calkit run`, and the session carries on as a shell afterwards.
With `attach`, an agent's PID, it attaches to the tmux pane the agent runs
in instead.
Sessions aren't supported on Windows yet.
Attaching sends the session's recent output first, so a reattaching
browser sees the screen.
The first message of that replay has `reset: true`, telling the browser to
clear the terminal before writing it.

The Operator sends `{"type": "sessions.output", "session": ..., "data":
...}` to attached channels, coalescing output over 20 milliseconds, and
`{"type": "sessions.exit", "session": ..., "code": ...}` when a session's
shell exits.

## Workspace actions

These act on a workspace with Git, DVC, and the network, so the Operator
runs them in a thread, one at a time per workspace, and replies when
they're done.
Each takes `id` and `workspace`, and only `workspace.status`,
`workspace.git_status`, `workspace.run_log`, and `workspace.agent_log`
work on managed workspaces, which are checked out with `--force` to run
stages.
`workspace.git_status`, `workspace.run_log`, and `workspace.agent_log`
never wait on another action, and while a run goes, `workspace.status` and `workspace.stop`
don't either.

| Browser sends          | Other fields                                                          |
| ---------------------- | --------------------------------------------------------------------- |
| `workspace.status`     | `fetch`                                                               |
| `workspace.git_status` | `fetch`                                                               |
| `workspace.pull`       | `merge`                                                               |
| `workspace.push`       |                                                                       |
| `workspace.save`       | `paths`, `message`, `to` (`git` or `dvc`), `push`                     |
| `workspace.ignore`     | `path`, `commit`                                                      |
| `workspace.run`        | `stages`                                                              |
| `workspace.run_log`    |                                                                       |
| `workspace.agent_log`  | `pid`, `limit`                                                        |
| `workspace.stop`       |                                                                       |
| `workspace.new`        | `branch`                                                              |
| `workspace.discard`    |                                                                       |
| `workspace.add_stage`  | `name`, `cmd`, `deps`, `outs`, `calkit_type`, `calkit_object`, `push` |

`workspace.status` returns what `calkit status --json` reports as
`status`, plus `stages`, every stage in the pipeline in order, each with
its `name`, `kind`, `state` (`running`, `stale`, or `ok`), the indexes of
the `questions` whose evidence it makes, and the ones it only feeds, being
upstream of that (`feeds_questions`).
`workspace.git_status` returns the Git part of `workspace.status`, which is
quick, while the rest can take a while for a large pipeline, so the
browser asks for both and shows Git's first.
`workspace.pull` only fast-forwards, returning `diverged` when it can't,
unless `merge` is true, in which case it merges, undoing a merge that
conflicts.

`workspace.agent_log` returns the end of a running agent's conversation as
`entries`, each with a `role` (`user`, `assistant`, or `tool`), `text`, and
`time`, read from the log the agent keeps, or `null` for one whose log
can't be read, e.g., opencode's.

`workspace.run` runs without a terminal and replies when it's done, with
`ok` and the end of its `output`; meanwhile the browser follows it with
`workspace.run_log`, which returns the latest run's log `name`, named by
when it started, and the end of the `log`, however that run was started.
`workspace.stop` interrupts the run in progress, as Ctrl+C would.
`workspace.new` runs `calkit new workspace` to make another workspace for
the project on `branch`, a Git worktree sharing the workspace's DVC cache,
beside it if it's in `~/calkit` or `~/dev`, where the Operator finds it,
else in `~/calkit`, and returns its `path`.

`workspaces.clone`, with `id` and `git_repo_url`, clones a project into
`~/calkit` with the machine's own Git credentials, where it becomes a
workspace, and returns its `path`.

## Editor builds

The figure and LaTeX editors send `build.start` with `id`, `project`
(`owner/name`), `stages`, `commit`, and `files`, a list of
`{"path": ..., "contents": ...}` for the editor's unsaved files only.
For a save, it also has `save` true, `message`, and `branch`, i.e., `main`
or a change batch's branch.
The Operator answers with `{"build": ...}` once it has queued the build,
then sends:

- `{"type": "build.log", "build": ..., "data": ...}` as the build runs.
- `{"type": "build.done", "build": ..., "ok": ..., "outputs": ...}` when
  it finishes, with `outputs` a list of `{"path": ..., "url": ...}`, each
  URL short-lived, and for a save, `commit`, the commit it pushed.

To upload outputs, the Operator calls `POST /operators/builds` with its
Operator token and the project, and gets back presigned upload URLs and
download URLs, which expire after a day.

Like everything on a channel, builds only run for channels opened with a
valid grant.
