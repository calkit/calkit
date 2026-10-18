import { describe, expect, it } from "vitest"

import { signMessage, signedText } from "./connection"

function fromBase64Url(value: string): Uint8Array {
  const binary = atob(value.replace(/-/g, "+").replace(/_/g, "/"))
  return Uint8Array.from(binary, (c) => c.charCodeAt(0))
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

describe("signMessage", () => {
  it("signs what the Operator checks", async () => {
    // Signed by the Operator's test (calkit/tests/test_operator.py), which
    // checks the same vector, so both ends sign the same text the same way
    const vector = {
      jwk: {
        kty: "EC",
        crv: "P-256",
        x: "QF8jZqZXlCI2kwXe6F3IGC3DlMRjap4e8f1DV0uWNiQ",
        y: "GAhXTzjif_yPldGN07yo6alEe_o-IyFSC83KEKILGdE",
      },
      seq: 7,
      body: '{"type":"sessions.input","session":"s1","data":"ls ─\\n"}',
      sig: "Cml8CVzkHw2lLu6pU4A4BLtI17I6xUkJ_onoD76cKc10ZP4CjQ6_-XvcP3DmUqpni_b8crjTTi1SDU8jBZpumw",
    }
    expect(signedText(7, "{}")).toBe("calkit-operator-message\n7\n{}")
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
