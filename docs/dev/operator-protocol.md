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
  Operator is alive and what workspaces it has, and returns the relay URL
  and an Operator relay token.
  Operators check in every 60 seconds while running.
- `POST /operators/{operator_id}/relay-token`, with the user's token,
  returns the relay URL and a browser relay token for that Operator.
  This is where two-factor authentication will be required.
- `GET /projects/{owner}/{name}/workspaces` lists the project's workspaces
  across the user's Operators, from their latest check-ins.

## Relay

The relay serves two websocket endpoints, each taking its token as a
`token` query parameter, since browsers can't set headers on websockets:

- `/operator`, one connection per Operator.
  A new connection replaces an existing one for the same Operator.
- `/browser`, any number per Operator.
  Closes with code 4404 if the Operator isn't connected.

When a browser connects, the relay assigns it a channel ID and sends the
Operator `{"type": "channel.open", "ch": ..., "user_id": ...}`.
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
Attaching sends the session's recent output first, so a reattaching
browser sees the screen.

The Operator sends `{"type": "sessions.output", "session": ..., "data":
...}` to attached channels, coalescing output over 20 milliseconds, and
`{"type": "sessions.exit", "session": ..., "code": ...}` when a session's
shell exits.

## LaTeX builds

The browser sends `latex.build` with `id`, `project` (`owner/name`),
`stage`, `commit`, and `files`, a list of `{"path": ..., "contents": ...}`
for the editor's unsaved files only.
The Operator answers with `{"build": ...}` once it has queued the build,
then sends:

- `{"type": "latex.log", "build": ..., "data": ...}` as the build runs.
- `{"type": "latex.done", "build": ..., "ok": ..., "pdf_url": ...}` when
  it finishes, with `pdf_url` a short-lived URL to the uploaded PDF, or
  null if there's no PDF.

To upload, the Operator calls `POST /operators/builds` with its Operator
token and the project, and gets back a presigned upload URL and a
download URL, which expire after a day.

The Operator only accepts channels whose `user_id` is its owner's.
