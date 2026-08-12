import { describe, expect, it } from "vitest";
import { isUnsupportedByHub, RequestFailed } from "./messages";

describe("isUnsupportedByHub", () => {
  it("recognizes a route the hub does not have", () => {
    // What a hub older than the extension sends back, and all it sends:
    // FastAPI's own 404 body for a route that was never registered
    expect(isUnsupportedByHub(new RequestFailed("Not Found", false, 404))).toBe(
      true,
    );
  });

  it("leaves other hub errors alone", () => {
    expect(
      isUnsupportedByHub(new RequestFailed("Not signed in", true, 401)),
    ).toBe(false);
    expect(isUnsupportedByHub(new RequestFailed("Boom", false, 500))).toBe(
      false,
    );
  });

  it("does not treat a failure that never reached a hub as a version gap", () => {
    // No status means the service worker itself was unreachable, which
    // says nothing about what the hub supports
    expect(isUnsupportedByHub(new RequestFailed("No response", false))).toBe(
      false,
    );
    expect(isUnsupportedByHub(new Error("Not Found"))).toBe(false);
  });
});
