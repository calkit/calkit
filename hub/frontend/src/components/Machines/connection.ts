import { MachinesService } from "../../client"

export interface SessionInfo {
  id: string
  workspace: string
  label: string
  attached: number
}

type Listener = (msg: any) => void

// Signed along with each message, so a signature means nothing elsewhere.
// The link checks the same text (calkit/hub_link.py).
export const MESSAGE_SIGNATURE_CONTEXT = "calkit-machine-message"
// Signed along with each of the link's replies, as is the ID of the
// grant the channel was opened with, so a reply is good on that one only
export const REPLY_SIGNATURE_CONTEXT = "calkit-machine-reply"

export function signedText(seq: number, body: string): string {
  return `${MESSAGE_SIGNATURE_CONTEXT}\n${seq}\n${body}`
}

export function replyText(grantId: string, seq: number, body: string): string {
  return `${REPLY_SIGNATURE_CONTEXT}\n${grantId}\n${seq}\n${body}`
}

function toBase64Url(bytes: ArrayBuffer): string {
  let binary = ""
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

// A message as the link takes it: its JSON text, signed as sent with
// this connection's key, right after the last one, so the relay can
// neither forge, replay, nor drop one
export async function signMessage(
  key: CryptoKey,
  seq: number,
  body: string,
): Promise<{ seq: number; body: string; sig: string }> {
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    new TextEncoder().encode(signedText(seq, body)),
  )
  return { seq, body, sig: toBase64Url(sig) }
}

// The machine's public key, as the API gives it over HTTPS, never the relay
export function importMachineKey(jwk: {
  x: string
  y: string
}): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "jwk",
    { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y },
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  )
}

// A frame from the relay, opened if the link signed it for this channel
// right after the last one, else refused, since the relay could have
// forged, replayed, reordered, or dropped something
export async function openReply(
  key: CryptoKey,
  grantId: string,
  lastSeq: number,
  data: unknown,
): Promise<Record<string, any>> {
  if (typeof data !== "string") throw new Error("Reply isn't text")
  const frame = JSON.parse(data)
  const { seq, body, sig } = frame ?? {}
  if (seq !== lastSeq + 1) throw new Error("Reply is out of sequence")
  if (
    typeof body !== "string" ||
    typeof sig !== "string" ||
    !/^[A-Za-z0-9_-]+$/.test(sig)
  ) {
    throw new Error("Reply is malformed")
  }
  const sigBytes = Uint8Array.from(
    atob(sig.replace(/-/g, "+").replace(/_/g, "/")),
    (c) => c.charCodeAt(0),
  )
  const verified = await crypto.subtle.verify(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    sigBytes,
    new TextEncoder().encode(replyText(grantId, seq, body)),
  )
  if (!verified) throw new Error("Reply signature is invalid")
  const msg = JSON.parse(body)
  if (typeof msg !== "object" || msg === null || Array.isArray(msg)) {
    throw new Error("Reply is malformed")
  }
  return msg
}

// One WebSocket's channel to the link: the keys each end signs with,
// and how far each has got
interface Channel {
  ws: WebSocket
  key: CryptoKey
  seq: number
  // Signing is asynchronous, so messages queue to keep their order
  outbound: Promise<void>
  machineKey: CryptoKey
  grantId: string
  replySeq: number
  // As is checking replies
  inbound: Promise<void>
  ready: boolean
}

// Why the hub refused a relay token, from app/users.py
export const SECOND_FACTOR_SETUP_REQUIRED =
  "Two-factor authentication setup required"
export const SECOND_FACTOR_REQUIRED = "Two-factor authentication code required"

// How long a request waits for its answer, except those that run Git, DVC,
// or the pipeline, which take as long as those do
export const REQUEST_TIMEOUT_MS = 2 * 60 * 1000
const UNTIMED_REQUESTS = new Set([
  "workspace.run",
  "workspace.pull",
  "workspace.push",
  "workspace.save",
  "workspace.new",
  "workspaces.clone",
])
// How long the link has to accept the channel once the relay has it
const READY_TIMEOUT_MS = 20 * 1000

// One browser connection to a machine through the relay, opened while
// the machine is online. See docs/dev/hub-link-protocol.md for the
// messages.
export class MachineConnection {
  machineId: string
  channel: Channel | null = null
  // Bumped on each attempt to connect, so a stale one gives up
  attempt = 0
  nextId = 1
  pending = new Map<
    number,
    { resolve: (r: any) => void; reject: (e: Error) => void }
  >()
  sessionListeners = new Map<string, Set<Listener>>()
  statusListeners = new Set<() => void>()
  // Only once the link has accepted the channel, in a signed reply
  connected = false
  // Connected at some point since the page opened
  wasConnected = false
  closed = true
  // Why connecting failed, if the user has to do something about it
  error: string | null = null
  retryDelay = 1000
  retryTimer: ReturnType<typeof setTimeout> | undefined = undefined

  constructor(machineId: string) {
    this.machineId = machineId
  }

  open() {
    if (!this.closed) return
    this.closed = false
    this.retryDelay = 1000
    this.connect()
  }

  async connect() {
    clearTimeout(this.retryTimer)
    const attempt = ++this.attempt
    let channel: Channel
    let token: string
    try {
      // A key for this connection only, which can't leave the browser. Its
      // public half goes in the grant the link checks, so the relay
      // carrying the grant can't use it.
      const keys = await crypto.subtle.generateKey(
        { name: "ECDSA", namedCurve: "P-256" },
        false,
        ["sign", "verify"],
      )
      const jwk = await crypto.subtle.exportKey("jwk", keys.publicKey)
      const resp = await MachinesService.postMachineRelayToken(
        {
          machine_id: this.machineId,
          relayTokenReq: {
            public_key: {
              kty: "EC",
              crv: "P-256",
              x: jwk.x ?? "",
              y: jwk.y ?? "",
            },
          },
        },
        // For the second factor's cookie
        { withCredentials: true },
      )
      // Closed while the token was on its way, e.g., by leaving the page,
      // so it mustn't open a channel that would keep the machine awake
      if (this.closed || attempt !== this.attempt) return
      const { relay_url, machine_public_key, grant_id } = resp.data
      token = resp.data.token
      const machineKey = await importMachineKey(machine_public_key)
      if (this.closed || attempt !== this.attempt) return
      const ws = new WebSocket(`${relay_url}/browser`)
      channel = {
        ws,
        key: keys.privateKey,
        seq: 0,
        outbound: Promise.resolve(),
        machineKey,
        grantId: grant_id,
        replySeq: 0,
        inbound: Promise.resolve(),
        ready: false,
      }
    } catch (e: any) {
      if (attempt !== this.attempt) return
      const detail = e.response?.data?.detail
      // Retrying won't help until the user enters a code
      if (
        detail === SECOND_FACTOR_REQUIRED ||
        detail === SECOND_FACTOR_SETUP_REQUIRED
      ) {
        this.error = detail
        this.notify()
        return
      }
      this.scheduleReconnect()
      return
    }
    this.error = null
    const previous = this.channel
    this.channel = channel
    if (previous) {
      previous.ws.close()
      this.connected = false
      this.rejectPending()
    }
    const { ws } = channel
    const isCurrent = () => this.channel === channel
    // Sent in a message rather than the URL to stay out of logs, and the
    // channel isn't used until the link says it's ready
    let readyTimer: ReturnType<typeof setTimeout> | undefined
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "auth", token }))
      readyTimer = setTimeout(() => {
        if (!channel.ready) ws.close()
      }, READY_TIMEOUT_MS)
    }
    ws.onmessage = (event) => {
      // Checked in order, and once one fails nothing after it counts
      channel.inbound = channel.inbound.then(async () => {
        if (!isCurrent()) return
        let msg: Record<string, any>
        try {
          msg = await openReply(
            channel.machineKey,
            channel.grantId,
            channel.replySeq,
            event.data,
          )
        } catch (e) {
          console.warn("Dropping machine connection:", e)
          this.channel = null
          ws.close()
          this.disconnected()
          return
        }
        channel.replySeq += 1
        if (!channel.ready) {
          if (msg.type !== "channel.ready") {
            this.channel = null
            ws.close()
            this.disconnected()
            return
          }
          channel.ready = true
          clearTimeout(readyTimer)
          this.connected = true
          this.wasConnected = true
          this.retryDelay = 1000
          this.notify()
          return
        }
        this.receive(msg)
      })
      // A listener's error mustn't hold up the replies after it
      channel.inbound = channel.inbound.catch((e) => console.error(e))
    }
    ws.onclose = () => {
      clearTimeout(readyTimer)
      // A newer connection has taken over, or this one was already dropped
      if (!isCurrent()) return
      this.channel = null
      this.disconnected()
    }
  }

  rejectPending() {
    for (const p of this.pending.values()) {
      p.reject(new Error("Disconnected from machine"))
    }
    this.pending.clear()
  }

  // Whatever was waiting on the connection gives up, and it's tried again
  disconnected() {
    this.connected = false
    this.rejectPending()
    this.notify()
    this.scheduleReconnect()
  }

  receive(msg: Record<string, any>) {
    if (msg.type === "result" || msg.type === "error") {
      const p = this.pending.get(msg.id)
      if (p) {
        this.pending.delete(msg.id)
        if (msg.type === "result") p.resolve(msg.result)
        else p.reject(new Error(msg.error))
      }
      return
    }
    for (const listener of this.sessionListeners.get(msg.session) ?? []) {
      listener(msg)
    }
  }

  scheduleReconnect() {
    if (this.closed) return
    clearTimeout(this.retryTimer)
    this.retryTimer = setTimeout(() => this.connect(), this.retryDelay)
    this.retryDelay = Math.min(this.retryDelay * 2, 30000)
  }

  notify() {
    for (const listener of this.statusListeners) listener()
  }

  send(msg: object) {
    const channel = this.channel
    if (!channel?.ready || channel.ws.readyState !== WebSocket.OPEN) return
    const body = JSON.stringify(msg)
    channel.outbound = channel.outbound
      .then(async () => {
        channel.seq += 1
        const signed = await signMessage(channel.key, channel.seq, body)
        if (channel.ws.readyState === WebSocket.OPEN) {
          channel.ws.send(JSON.stringify(signed))
        }
      })
      // The link takes each message only right after the last, so
      // one that can't be signed means starting over
      .catch(() => channel.ws.close())
  }

  request(type: string, fields: object = {}): Promise<any> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      if (!this.connected) {
        reject(new Error("Not connected to machine"))
        return
      }
      const timer = UNTIMED_REQUESTS.has(type)
        ? undefined
        : setTimeout(() => {
            this.pending.delete(id)
            reject(new Error("The machine didn't answer in time"))
          }, REQUEST_TIMEOUT_MS)
      this.pending.set(id, {
        resolve: (r) => {
          clearTimeout(timer)
          resolve(r)
        },
        reject: (e) => {
          clearTimeout(timer)
          reject(e)
        },
      })
      this.send({ type, id, ...fields })
    })
  }

  onSession(session: string, listener: Listener) {
    let listeners = this.sessionListeners.get(session)
    if (!listeners) {
      listeners = new Set()
      this.sessionListeners.set(session, listeners)
    }
    listeners.add(listener)
    return () => listeners.delete(listener)
  }

  retryNow() {
    this.error = null
    this.retryDelay = 1000
    if (!this.closed) this.connect()
  }

  async waitUntilConnected(timeoutMs = 10000) {
    const start = Date.now()
    while (!this.connected) {
      if (Date.now() - start > timeoutMs) {
        throw new Error("Could not connect to machine")
      }
      await new Promise((resolve) => setTimeout(resolve, 200))
    }
  }

  // Until opened again, e.g., when the machine comes back online
  close() {
    this.closed = true
    this.attempt += 1
    clearTimeout(this.retryTimer)
    const channel = this.channel
    this.channel = null
    channel?.ws.close()
    if (channel || this.connected) {
      this.connected = false
      this.rejectPending()
      this.notify()
    }
  }
}

export interface Pane {
  machineId: string
  session: string
}
