import { OperatorsService } from "../../client"
import { getSecondFactorToken } from "../../lib/auth"

export interface SessionInfo {
  id: string
  workspace: string
  label: string
  attached: number
}

type Listener = (msg: any) => void

// Signed along with each message, so a signature means nothing elsewhere.
// The Operator checks the same text (calkit/operator.py).
export const MESSAGE_SIGNATURE_CONTEXT = "calkit-operator-message"

export function signedText(seq: number, body: string): string {
  return `${MESSAGE_SIGNATURE_CONTEXT}\n${seq}\n${body}`
}

function toBase64Url(bytes: ArrayBuffer): string {
  let binary = ""
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

// A message as the Operator takes it: its JSON text, signed as sent with
// this connection's key, after the last one, so the relay can neither
// forge nor replay one
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

// What one connection signs its messages with, in the order they're sent
interface Signer {
  key: CryptoKey
  seq: number
  queue: Promise<void>
}

// Why the hub refused a relay token, from app/users.py
export const SECOND_FACTOR_SETUP_REQUIRED =
  "Two-factor authentication setup required"
export const SECOND_FACTOR_REQUIRED = "Two-factor authentication code required"

// One browser connection to an Operator through the relay. See
// docs/dev/operator-protocol.md for the messages.
export class OperatorConnection {
  operatorId: string
  ws: WebSocket | null = null
  signer: Signer | null = null
  nextId = 1
  pending = new Map<
    number,
    { resolve: (r: any) => void; reject: (e: Error) => void }
  >()
  sessionListeners = new Map<string, Set<Listener>>()
  statusListeners = new Set<() => void>()
  connected = false
  closed = false
  // Why connecting failed, if the user has to do something about it
  error: string | null = null
  retryDelay = 1000

  constructor(operatorId: string) {
    this.operatorId = operatorId
    this.connect()
  }

  async connect() {
    let ws: WebSocket
    let signer: Signer
    try {
      // A key for this connection only, which can't leave the browser. Its
      // public half goes in the grant the Operator checks, so the relay
      // carrying the grant can't use it.
      const keys = await crypto.subtle.generateKey(
        { name: "ECDSA", namedCurve: "P-256" },
        false,
        ["sign", "verify"],
      )
      const jwk = await crypto.subtle.exportKey("jwk", keys.publicKey)
      signer = { key: keys.privateKey, seq: 0, queue: Promise.resolve() }
      const resp = await OperatorsService.postOperatorRelayToken({
        operator_id: this.operatorId,
        "x-second-factor": getSecondFactorToken(),
        relayTokenReq: {
          public_key: {
            kty: "EC",
            crv: "P-256",
            x: jwk.x ?? "",
            y: jwk.y ?? "",
          },
        },
      })
      // Closed while the token was on its way, e.g., by leaving the page,
      // so it mustn't open a channel that would keep the Operator awake
      if (this.closed) return
      const { relay_url, token } = resp.data
      ws = new WebSocket(`${relay_url}/browser`)
      // Sent in a message rather than the URL to stay out of logs
      ws.addEventListener("open", () =>
        ws.send(JSON.stringify({ type: "auth", token })),
      )
    } catch (e: any) {
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
    this.ws = ws
    this.signer = signer
    ws.onopen = () => {
      this.connected = true
      this.retryDelay = 1000
      this.notify()
    }
    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
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
    ws.onclose = () => {
      this.connected = false
      this.ws = null
      this.signer = null
      for (const p of this.pending.values()) {
        p.reject(new Error("Disconnected from Operator"))
      }
      this.pending.clear()
      this.notify()
      this.scheduleReconnect()
    }
  }

  scheduleReconnect() {
    if (this.closed) return
    window.setTimeout(() => this.connect(), this.retryDelay)
    this.retryDelay = Math.min(this.retryDelay * 2, 30000)
  }

  notify() {
    for (const listener of this.statusListeners) listener()
  }

  send(msg: object) {
    const ws = this.ws
    const signer = this.signer
    if (ws?.readyState !== WebSocket.OPEN || !signer) return
    const body = JSON.stringify(msg)
    // Signing is asynchronous, so messages queue to keep their order
    signer.queue = signer.queue
      .then(async () => {
        signer.seq += 1
        const signed = await signMessage(signer.key, signer.seq, body)
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(signed))
      })
      .catch(() => {})
  }

  request(type: string, fields: object = {}): Promise<any> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState !== WebSocket.OPEN) {
        reject(new Error("Not connected to Operator"))
        return
      }
      this.pending.set(id, { resolve, reject })
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
    this.connect()
  }

  async waitUntilConnected(timeoutMs = 10000) {
    const start = Date.now()
    while (!this.connected) {
      if (Date.now() - start > timeoutMs) {
        throw new Error("Could not connect to Operator")
      }
      await new Promise((resolve) => window.setTimeout(resolve, 200))
    }
  }

  close() {
    this.closed = true
    this.ws?.close()
  }
}

export interface Pane {
  operatorId: string
  session: string
}
