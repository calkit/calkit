import { afterEach, describe, expect, it, vi } from "vitest"

import { MachinesService } from "../../client"
import {
  MachineConnection,
  importMachineKey,
  openReply,
  replyText,
  signMessage,
  signedText,
} from "./connection"

vi.mock("../../client", () => ({
  MachinesService: { postMachineRelayToken: vi.fn() },
}))

function fromBase64Url(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"))
  return Uint8Array.from(binary, (c) => c.charCodeAt(0))
}

function toBase64Url(bytes: ArrayBuffer): string {
  let binary = ""
  for (const byte of new Uint8Array(bytes)) binary += String.fromCharCode(byte)
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "")
}

async function verify(
  jwk: JsonWebKey,
  signed: { seq: number; body: string; sig: string },
) {
  const key = await crypto.subtle.importKey(
    "jwk",
    jwk,
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  )
  return crypto.subtle.verify(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    fromBase64Url(signed.sig),
    new TextEncoder().encode(signedText(signed.seq, signed.body)),
  )
}

// A frame as the link sends it
async function signReply(
  key: CryptoKey,
  grantId: string,
  seq: number,
  msg: object,
): Promise<string> {
  const body = JSON.stringify(msg)
  const sig = await crypto.subtle.sign(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    new TextEncoder().encode(replyText(grantId, seq, body)),
  )
  return JSON.stringify({ seq, body, sig: toBase64Url(sig) })
}

async function generateMachineKeys() {
  const keys = await crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    true,
    ["sign", "verify"],
  )
  const jwk = await crypto.subtle.exportKey("jwk", keys.publicKey)
  return {
    privateKey: keys.privateKey,
    jwk: { x: jwk.x ?? "", y: jwk.y ?? "" },
  }
}

class FakeWebSocket {
  static OPEN = 1
  static instances: FakeWebSocket[] = []
  url: string
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }
  send(data: string) {
    this.sent.push(data)
  }
  close() {
    if (this.readyState === 3) return
    this.readyState = 3
    this.onclose?.()
  }
  accept() {
    this.readyState = 1
    this.onopen?.()
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  FakeWebSocket.instances = []
})

describe("signMessage", () => {
  it("signs what the link checks", async () => {
    // Signed by the link's test (calkit/tests/hub/test_link.py), which
    // checks the same vector, so both ends sign the same text the same way
    const vector = {
      jwk: {
        kty: "EC",
        crv: "P-256",
        x: "ZfNFdAzsfpIWhDie2L9NwSNt6d6a2lwlSMf3MzH-XVk",
        y: "Hh0kg1uyGNF6Zd34yhdohtFps5dU_GcMu5ZyZ-YL7LM",
      },
      seq: 7,
      body: '{"type":"sessions.input","session":"s1","data":"ls ─\\n"}',
      sig: "xshOHd9lW3FQS3_FXFFzmZU8wWUPdrVR6VmguNFs9Xr-kxLc2jzVSXqYlOfXn9DWeTjonww_5a6Rio0iIGGpZA",
    }
    expect(signedText(7, "{}")).toBe("calkit-machine-message\n7\n{}")
    expect(await verify(vector.jwk, vector)).toBe(true)
    expect(await verify(vector.jwk, { ...vector, seq: 8 })).toBe(false)
    // And what this end signs verifies with the public key it sends
    const keys = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["sign", "verify"],
    )
    const jwk = await crypto.subtle.exportKey("jwk", keys.publicKey)
    const body = JSON.stringify({ type: "sessions.list", id: 1 })
    const signed = await signMessage(keys.privateKey, 1, body)
    expect(signed.body).toBe(body)
    expect(fromBase64Url(signed.sig)).toHaveLength(64)
    expect(signed.sig).not.toMatch(/[+/=]/)
    expect(await verify(jwk, signed)).toBe(true)
  })
})

describe("openReply", () => {
  it("opens only the link's replies for this channel, in order", async () => {
    expect(replyText("g", 1, "{}")).toBe("calkit-machine-reply\ng\n1\n{}")
    // Signed with Python's cryptography as the link signs, so both ends
    // agree on the text and encoding
    const vector = {
      jwk: {
        x: "DPLpRtfVMoc5Ym_OxUQESNigOKHp_0PSeevg5ixXoG4",
        y: "yxGTKYCbKo3idx-9brKxpv9vsipfal9VL731aHJ8L0U",
      },
      grantId: "3f9c1e2a-7b4d-4e8f-9a0b-1c2d3e4f5a6b",
      frame: JSON.stringify({
        seq: 3,
        body: '{"type": "result", "id": 2, "result": {"public_key": "ssh-ed25519 AAAA ─ me@host"}}',
        sig: "WobqWZ5dnbSEdEon79x_YFqp5qaCt9oCRJXS7UQOjuS7S29yan0PAheCB5nRkoMFWyu9VD6dlqO5SbNcKZoEyA",
      }),
    }
    const vectorKey = await importMachineKey(vector.jwk)
    expect(await openReply(vectorKey, vector.grantId, 2, vector.frame)).toEqual(
      {
        type: "result",
        id: 2,
        result: { public_key: "ssh-ed25519 AAAA ─ me@host" },
      },
    )
    // A good reply, and the same reply as anything else
    const machine = await generateMachineKeys()
    const key = await importMachineKey(machine.jwk)
    const ready = { type: "channel.ready" }
    const good = await signReply(machine.privateKey, "g1", 1, ready)
    expect(await openReply(key, "g1", 0, good)).toEqual(ready)
    // Repeated or after a gap
    await expect(openReply(key, "g1", 1, good)).rejects.toThrow("sequence")
    const later = await signReply(machine.privateKey, "g1", 3, ready)
    await expect(openReply(key, "g1", 1, later)).rejects.toThrow("sequence")
    // For another channel
    await expect(openReply(key, "g2", 0, good)).rejects.toThrow("signature")
    // Signed by someone else, e.g., the relay
    const relay = await generateMachineKeys()
    const forged = await signReply(relay.privateKey, "g1", 1, ready)
    await expect(openReply(key, "g1", 0, forged)).rejects.toThrow("signature")
    // Changed on the way
    const tampered = JSON.parse(good)
    tampered.body = JSON.stringify({ type: "channel.ready", extra: true })
    await expect(
      openReply(key, "g1", 0, JSON.stringify(tampered)),
    ).rejects.toThrow("signature")
    // Unsigned or malformed
    await expect(
      openReply(key, "g1", 0, JSON.stringify({ seq: 1, body: "{}" })),
    ).rejects.toThrow("malformed")
    await expect(
      openReply(key, "g1", 0, JSON.stringify({ ...tampered, sig: "a+b/" })),
    ).rejects.toThrow("malformed")
    await expect(openReply(key, "g1", 0, "{")).rejects.toThrow()
    await expect(openReply(key, "g1", 0, new ArrayBuffer(4))).rejects.toThrow(
      "text",
    )
    const list = await signReply(machine.privateKey, "g1", 1, [])
    await expect(openReply(key, "g1", 0, list)).rejects.toThrow("malformed")
  })
})

describe("MachineConnection", () => {
  it("connects once the link is ready and drops on a bad reply", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket)
    const machine = await generateMachineKeys()
    const relayToken = vi.mocked(MachinesService.postMachineRelayToken)
    relayToken.mockResolvedValue({
      data: {
        relay_url: "wss://relay.example",
        token: "relay-token",
        machine_public_key: { kty: "EC", crv: "P-256", ...machine.jwk },
        grant_id: "g1",
      },
    } as any)
    const conn = new MachineConnection("m1")
    conn.open()
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toBe("wss://relay.example/browser")
    ws.accept()
    expect(JSON.parse(ws.sent[0])).toEqual({
      type: "auth",
      token: "relay-token",
    })
    // Open isn't enough: nothing goes out until the link says so
    expect(conn.connected).toBe(false)
    await expect(conn.request("sessions.list")).rejects.toThrow("Not connected")
    conn.send({ type: "sessions.input", session: "s1", data: "x" })
    const reply = (seq: number, msg: object) =>
      signReply(machine.privateKey, "g1", seq, msg)
    ws.onmessage?.({ data: await reply(1, { type: "channel.ready" }) })
    await vi.waitFor(() => expect(conn.connected).toBe(true))
    // Requests are signed with the key named in the grant, in sequence
    const request = conn.request("sessions.list")
    await vi.waitFor(() => expect(ws.sent).toHaveLength(2))
    const signed = JSON.parse(ws.sent[1])
    expect(signed.seq).toBe(1)
    const browserKey = relayToken.mock.calls[0][0].relayTokenReq.public_key
    expect(await verify(browserKey, signed)).toBe(true)
    const id = JSON.parse(signed.body).id
    ws.onmessage?.({
      data: await reply(2, { type: "result", id, result: { sessions: [] } }),
    })
    expect(await request).toEqual({ sessions: [] })
    // Session output goes to its listeners
    const output: any[] = []
    conn.onSession("s1", (msg) => output.push(msg))
    ws.onmessage?.({
      data: await reply(3, { type: "sessions.output", session: "s1" }),
    })
    await vi.waitFor(() => expect(output).toHaveLength(1))
    // A skipped reply drops the connection and what was waiting on it
    const pending = conn.request("sessions.list")
    ws.onmessage?.({
      data: await reply(5, { type: "sessions.output", session: "s1" }),
    })
    await expect(pending).rejects.toThrow("Disconnected")
    expect(ws.readyState).toBe(3)
    expect(conn.connected).toBe(false)
    expect(output).toHaveLength(1)
    expect(conn.retryTimer).toBeDefined()
    conn.close()
  })
})
