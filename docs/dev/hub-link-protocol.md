# Hub link protocol

<!-- prettier-ignore -->
!!! note
    This document was written by Anthropic's Claude Code.

How linked machines, the hub API, the relay, and browsers talk to each other.
The decisions behind it are in [ADR 0001](adrs/0001-linked-machines.md).

## Parties

- The **API** is the hub backend.
  It owns machine records and issues every token.
- The **relay** is a single-process service that pairs websockets.
  It has no database and trusts only JWTs signed with the API's secret.
- The **link** runs on a user's machine.
- The **browser** is the hub frontend.

## Tokens

| Token             | Form                           | Lifetime      | Used for                                    |
| ----------------- | ------------------------------ | ------------- | ------------------------------------------- |
| Machine token     | `ckm_` + selector and verifier | Until revoked | Authenticating the machine to the API       |
| Machine relay JWT | JWT with scope `relay:machine` | 10 minutes    | Opening the link's relay connection         |
| Browser relay JWT | JWT with scope `relay:browser` | 60 seconds    | Opening one browser connection to the relay |
| Machine CLI token | `ckp_` personal access token   | 365 days      | Calkit's CLI on the linked machine          |

Machine tokens are stored like personal access tokens: a selector to look
the record up and a hashed verifier.
The machine's CLI token is a personal access token the hub issues to the
machine, tied to it, and revoked with it.
Relay tokens are checked when a connection opens, and the link's again
when it refreshes its connection's.
Revoking a machine takes effect at its next check-in, when the API
rejects its token and the link shuts down, and at the relay within 10
minutes, once the relay token it can no longer refresh expires.

## API

- `POST /machines`, with the user's token, registers a machine and
  returns its ID, name, machine token, and `grant_public_key`.
  The token is only returned here.
  It takes the machine's own P-256 public key as a JSON Web Key,
  `public_key`, which a machine linked with `--ssh`, registered from
  another machine, sends at its first check-in instead.
  Names must match `^[a-z0-9][a-z0-9-]{0,63}$`, and a user can have at
  most 50 active machines.
  The owner is emailed whenever one is registered or revoked.
- `GET /machines` lists the user's machines.
- `DELETE /machines/{machine_id}` revokes one, which takes a web sign-in,
  as relay tokens do, not just the user's token.
  `DELETE /machines/self`, with the machine token, revokes the machine
  making the request, which is how `calkit hub link uninstall` does it.
- `POST /machines/check-in`, with the machine token, records that the
  link is alive, how it runs (`mode`: `service`, `foreground`, or
  `cron`), whether it's `connected` to the relay, and what workspaces it
  has, each with its Git state and pipeline run state: `running`,
  `running_stages`, `running_since`, and `last_run` (`status`, `started`,
  `ended`, and `failed_stages`), when it was last active
  (`last_activity`), whether `in_use_by` a link to another hub,
  which is always just `another hub`, and the coding agents running there
  (`agents`), and whether a restart is pending (`restart_pending`).
  A workspace's `project` is the hub project its DVC data goes to, from
  its default `ck://` or hub remote, so a fork is named for the fork,
  and otherwise what its `calkit.yaml` and Git remote say.
  Each agent, e.g., Claude Code, Codex, or opencode, is found by its
  command and working directory, however it was started, and has its
  `tool`, `pid`, when it `started`, `where` it runs (`session`, one of the
  link's, `tmux`, or another `terminal`), the `app` it was started
  from, e.g., `Code`, and the `name` and `status` it gives itself, if any.
  It also lists the sign-ins its open channels came from
  (`channel_sessions`, the grants' `sid`s), and its `public_key`, which
  the hub keeps the first time it's sent and never replaces.
  A different one gets 409, after which the link doesn't connect and
  `calkit hub link install` registers it again.
  It returns the relay URL, a machine relay token, `grant_public_key`,
  which grants are checked with, `connect`, which tells a link in
  cron mode whether to connect, `restart`, which
  passes on a restart its owner asked for, and `ended_sessions`, which of
  those sign-ins are no longer live, e.g., after a password change, whose
  channels the link then closes, leaving their sessions running.
  Links check in every 60 seconds while connected.
- `POST /machines/{machine_id}/wake`, with the user's token, asks a
  link in cron mode to connect at its next check-in.
  The request lapses after 15 minutes and is cleared once the link
  checks in connected.
- `POST /machines/{machine_id}/restart`, with the user's token, asks a
  machine's link to restart, which it hears at its next check-in.
- `POST /machines/{machine_id}/relay-token`, with the user's token,
  returns the relay URL and a browser relay token for that machine, along
  with the machine's `machine_public_key` and the `grant_id` of the
  grant in the token, which the browser checks replies with.
  The browser sends the public half of a P-256 key it made for this
  connection, whose private half can't be exported, as a JSON Web Key:
  `{"public_key": {"kty": "EC", "crv": "P-256", "x": ..., "y": ...}}`.
  It requires an access token from a person signing in to the web app,
  whose sign-in session is still live, not a personal access token or a
  CLI, CI, or GitHub token login, and proof that the session entered a
  two-factor code within the last 12 hours:
  the `second_factor` cookie `POST /user/totp/verify` (or `/confirm`)
  sets, which is HttpOnly and SameSite=Strict, and lasts 12 hours.
  Their responses, like `GET /user/totp`, say until when, as
  `verified_until`.
  The cookie's token names the session, so it's worthless to any other.
  Otherwise it answers 403 with a detail the browser recognizes, to prompt
  for setup or a code.
  It answers 409 if the machine is offline or hasn't sent its key yet.
  Setting up two-factor authentication (`POST /user/totp`) emails a code,
  which confirming takes along with one from the authenticator app.
  It, and registering a machine, require a verified email, and changing
  a verified email takes a signed-in session and a code sent to it for the
  new address.
- `POST /logout` ends the caller's sign-in session and clears the
  `second_factor` cookie, and `POST /user/sessions/end-others`, with a
  signed-in session, ends every other one.
  Changing the password or email, or turning off two-factor
  authentication, ends every other session too, and using a rotated
  refresh token after its grace window ends its own.
- `POST /machines/{machine_id}/cli-token-request`, which takes what a
  relay token does, lets that machine's link fetch a CLI token for it
  within the next 10 minutes.
  `POST /machines/cli-token`, with the machine token, then returns
  `{"token": ...}`, a personal access token for the owner with full scope
  that lasts 365 days, replacing any the machine was issued before, or 403
  if none was requested.
- `GET /projects/{owner}/{name}/workspaces` lists the project's workspaces
  across the user's machines, from their latest check-ins.

A machine is online if its latest check-in was connected and within the
last three minutes, and asleep if it's in cron mode, not online, and has
checked in within the last 15 minutes.
Links check in with `connected` false as they shut down, so they show
as offline or asleep right away.
The browser only connects to machines that are online, and closes its
connections to ones that go offline.

## Cron mode

On machines where long-running processes aren't allowed, e.g., a
cluster's login node, cron runs `calkit hub link start --mode cron` every
5 minutes and at boot, from `/`, where the Linux and macOS services run
too.
It checks in with `connected` false and exits unless `connect` is true.
If it is, it runs as usual until it has had no sessions and no browsers
for 15 minutes.
A lock file keeps one link running per machine, user, and hub.

## Restarts

A link restarts once nothing is using it, i.e., it has no sessions
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
On Windows, a running link holds files an upgrade replaces, so an
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

- `/machine`, one connection per machine.
  A new connection replaces an existing one for the same machine.
  The relay closes it with code 4401 once its token expires, so after
  each check-in the link sends the relay token it got,
  `{"type": "auth.refresh", "token": ...}`, which moves the deadline to
  that token's expiry if it's an unused one for the same machine and
  owner, and is ignored otherwise.
- `/browser`, any number per machine.
  Closes with code 4404 if the machine isn't connected, and 4401 if the
  token's user isn't the machine's owner.

When a browser connects, the relay assigns it a channel ID and sends the
link `{"type": "channel.open", "ch": ..., "user_id": ..., "grant": ...}`.
The link ignores frames whose channel ID doesn't match
`[A-Za-z0-9_-]{1,64}`.
The grant, which comes from the browser's relay token, is an EdDSA JWT
the API signed, with the machine's ID as `aud`, its owner as `sub`, a
`jti`, `iat`, a 60 second `exp`, the browser's public key as `cnf.jwk`,
the sign-in it came from as `sid`, and when the second factor that let it
be issued expires as `tfa_exp`.
The link checks it against the `grant_public_key` from its latest
check-in, which comes over HTTPS, closing its open channels if that
changes.
It refuses channels without a valid, unused grant, or while it hasn't
checked in for 10 minutes, with `channel.close`.
Grant IDs it has used are kept in `used-grants.json` in its directory, so
they stay used across restarts.
Browser messages are forwarded to the link as
`{"type": "channel.message", "ch": ..., "msg": ...}`,
and the link sends `{"ch": ..., "msg": ...}` to reach a browser, which
receives `msg` unwrapped.
Each browser message is sent signed, as
`{"seq": ..., "body": ..., "sig": ...}`, where `body` is the message's
JSON text, `seq` counts up from 1 on each connection, and `sig` is an
ECDSA P-256 SHA-256 signature, as r and s side by side in base64url, of
`calkit-machine-message\n{seq}\n{body}` with the key the grant names.
A message whose signature doesn't check out, or whose `seq` isn't exactly
one past the last, closes the channel, so the relay, which carries the
grant, can neither use it nor forge, replay, drop, or reorder messages in
a channel a user opened.

What the link sends back is signed the same way, with its own key,
over `calkit-machine-reply\n{grant_id}\n{seq}\n{body}`, where `grant_id`
is the grant's `jti`, so a reply only counts on its own channel, and
`seq` counts up from 1 on each channel.
The first reply is always `{"type": "channel.ready"}`, which the browser
waits for before sending anything, closing the connection if it doesn't
come within 20 seconds.
The browser checks every reply with the `machine_public_key` from the
API, not the relay, and closes the connection over one that doesn't check
out or isn't next, reconnecting with a new key and grant.
So the relay can read both directions, e.g., what's typed in a terminal
and what it shows, but can't forge, drop, or reorder anything.
When a browser disconnects, the link gets
`{"type": "channel.close", "ch": ...}`.
The link sends the same to close a channel itself, and the relay
closes the browser with code 4401.
It does that when the channel's sign-in ends, its second factor expires
(`tfa_exp`), the grant key changes, the link hasn't checked in for 10
minutes, or more than 8 MiB of replies are waiting to go to the browser.
When the link disconnects, its browsers are closed with code 4410.

All messages are JSON text frames, and binary ones close the connection
with code 1003.
Messages over 256 KiB close the connection with code 1009, and the relay
runs with uvicorn's `--ws-max-size 300000` and `--ws-max-queue 4`, and
without permessage-deflate, so larger ones are refused before they're
buffered.
A reply too large to send becomes an error reply to its request, and is
dropped if it isn't one.
New connections close with code 1013 while 200 are waiting to send their
tokens, and a Traefik `inFlightReq` middleware allows each client address
50 connections at once.
The relay counts bytes in each direction per machine and logs them every
minute.

## Link messages

These are the `msg` payloads between a browser and a link.
Requests carry an `id`, answered by `{"type": "result", "id": ...,
"result": ...}` or `{"type": "error", "id": ..., "error": ...}`.
The browser gives up waiting after 2 minutes, except for `workspace.run`,
`workspace.pull`, `workspace.push`, `workspace.save`, `workspace.new`, and
`workspaces.clone`, which take as long as they take.

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

`sessions.open` starts a login shell in a workspace the link allows
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

The link sends `{"type": "sessions.output", "session": ..., "data":
...}` to attached channels, coalescing output over 20 milliseconds, and
`{"type": "sessions.exit", "session": ..., "code": ...}` when a session's
shell exits.

## Workspace actions

These act on a workspace with Git, DVC, and the network, so the link
runs them in a thread, one at a time per workspace, and replies when
they're done.
Each takes `id` and `workspace`, and only `workspace.status`,
`workspace.git_status`, `workspace.stages`, `workspace.run_log`, and
`workspace.agent_log` work on managed workspaces, which are checked out
with `--force` to run stages.
`workspace.git_status`, `workspace.stages`, `workspace.run_log`, and
`workspace.agent_log` never wait on another action, and while a run goes,
`workspace.status` and `workspace.stop` don't either.

| Browser sends          | Other fields                                                          |
| ---------------------- | --------------------------------------------------------------------- |
| `workspace.status`     | `fetch`                                                               |
| `workspace.git_status` | `fetch`                                                               |
| `workspace.stages`     |                                                                       |
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
`workspace.stages` likewise returns `stages` without the status, so with a
`state` of `null` and no questions.
`workspace.pull` only fast-forwards, returning `diverged` when it can't,
unless `merge` is true, in which case it merges, undoing a merge that
conflicts.
`workspace.pull` and `workspace.push` first remove the hub's token from
the local config of DVC remotes whose URL in the repo no longer matches
the one it was stored with, since a pull can point one anywhere.
`workspace.save` refuses `.dvc/config.local` and anything in
`.calkit/local`, which hold the machine's credentials.
Files the link reads or writes in a workspace itself, e.g., its lock
or a run's log, are never followed through links, since a repo can commit
links to anywhere.

`workspace.agent_log` returns the end of a running agent's conversation as
`entries`, each with a `role` (`user`, `assistant`, `tool`, or `event`,
e.g., a background task finishing), `text`, and `time`, read from the log the agent keeps, or `null` for one whose log
can't be read, e.g., opencode's.

`workspace.run` runs without a terminal and replies when it's done, with
`ok` and the end of its `output`; meanwhile the browser follows it with
`workspace.run_log`, which returns the latest run's log `name`, named by
when it started, and the end of the `log`, however that run was started.
`workspace.stop` interrupts the run in progress, as Ctrl+C would.
`workspace.new` runs `calkit new workspace` to make another workspace for
the project on `branch`, a Git worktree sharing the main checkout's DVC
cache, named after it and beside it if it's in `~/calkit` or `~/dev`,
where the link finds it, else in `~/calkit`, and returns its `path`.

`workspaces.clone`, with `id`, `git_repo_url`, and optionally `path`,
clones a project with the machine's own Git credentials and returns its
`path`.
Its `git_repo_url`, like `machine.check`'s, must be
`https://host[:port]/path` or `git@host:path`.
It goes in `~/calkit/<repo name>` unless `path` says otherwise, which can
start with `~/` and must be in the user's home folder, outside hidden
folders, and not exist yet.
A clone outside `~/calkit` and `~/dev`, or of a project that doesn't say
it's on the hub, is added to the config's workspaces, as
`calkit hub link add-workspace` would.

Before cloning, the hub asks what the machine still needs.
`machine.check`, with `id` and `git_repo_url`, returns `git_name` and
`git_email`, Git's identity there or null, `repo`, with the URL's `host`,
whether it's `ssh`, and an `error` if `git ls-remote` couldn't reach it
without prompting, and `token`, whether Calkit has a token for this
link's hub, which pulling and pushing data use.
`machine.configure`, with `id` and any of `git_name`, `git_email`, and
`token`, sets Git's global identity and, with `token` true, gets a CLI
token for the machine and stores it in Calkit's config, as
`calkit config set token` would.
The browser first calls `POST /machines/{machine_id}/cli-token-request`,
and the link then gets the token from `POST /machines/cli-token`
with its own token, so it never passes through the relay.
`machine.ssh_key`, with `id`, returns the machine's SSH `public_key`,
making an ed25519 key with no passphrase first if it has none, and
whether it was `created`, for the owner to add to their Git host, as
`calkit config github-ssh` does.
The check accepts a host's key the first time it connects, as someone
answering yes would.

## Editor builds

The figure and LaTeX editors send `build.start` with `id`, `project`
(`owner/name`), `stages`, `commit`, and `files`, a list of
`{"path": ..., "contents": ...}` for the editor's unsaved files only.
For a save, it also has `save` true, `message`, and `branch`, i.e., `main`
or a change batch's branch.
The link answers with `{"build": ...}` once it has queued the build,
then sends:

- `{"type": "build.log", "build": ..., "data": ...}` as the build runs.
- `{"type": "build.done", "build": ..., "ok": ..., "outputs": ...}` when
  it finishes, with `outputs` a list of `{"path": ..., "url": ...}`, each
  URL short-lived, and for a save, `commit`, the commit it pushed.

To upload outputs, the link calls `POST /machines/builds` with its
machine token and the project, and gets back presigned upload URLs and
download URLs, which expire after a day.

Like everything on a channel, builds only run for channels opened with a
valid grant.
