import { describe, expect, test } from "vitest";

import {
  isLoopbackHost,
  apiUrlFromHubUrl,
  isKnownHub,
  getHub,
  HUBS,
  resolveHubByWebUrl,
  visibleHubs,
} from "./hubs";

describe("apiUrlFromHubUrl", () => {
  test("puts the API on the api subdomain of the hub's host", () => {
    expect(apiUrlFromHubUrl("https://calkit.example.edu")).toBe(
      "https://api.calkit.example.edu",
    );
    // A missing scheme is filled in, https for a real host
    expect(apiUrlFromHubUrl("calkit.example.edu")).toBe(
      "https://api.calkit.example.edu",
    );
    // A trailing slash or path doesn't change the host
    expect(apiUrlFromHubUrl("https://calkit.example.edu/")).toBe(
      "https://api.calkit.example.edu",
    );
    // A port carries over, and a local host stays on http
    expect(apiUrlFromHubUrl("http://localhost:8000")).toBe(
      "http://api.localhost:8000",
    );
    expect(apiUrlFromHubUrl("localhost:8000")).toBe(
      "http://api.localhost:8000",
    );
    // A URL already naming the API host doesn't pick up a second prefix
    expect(apiUrlFromHubUrl("https://api.calkit.example.edu")).toBe(
      "https://api.calkit.example.edu",
    );
    expect(() => apiUrlFromHubUrl("not a url")).toThrow();
  });

  test("agrees with the built-in hubs, which are declared explicitly", () => {
    // Production and staging follow the rule, so the built-in entries and
    // the rule can't drift apart
    expect(apiUrlFromHubUrl(HUBS.production.webUrl)).toBe(
      HUBS.production.apiUrl,
    );
    expect(apiUrlFromHubUrl(HUBS.staging.webUrl)).toBe(HUBS.staging.apiUrl);
    // Local development predates the rule: its web app is on port 5173
    // while its API is on the default port, so it has to be declared
    expect(HUBS.local.apiUrl).toBe("http://api.localhost");
    expect(apiUrlFromHubUrl(HUBS.local.webUrl)).not.toBe(HUBS.local.apiUrl);
  });
});

describe("resolveHubByWebUrl", () => {
  test("matches a built-in however the hub URL was written", () => {
    // calkit.yaml may carry the hub with no scheme or a trailing slash,
    // and all of them have to land on the built-in local hub, whose API
    // is api.localhost. Deriving api.localhost:5173 instead points at a
    // host no credentials are stored under, which reads as "not signed in"
    for (const written of [
      "http://localhost:5173",
      "http://localhost:5173/",
      "localhost:5173",
    ]) {
      expect(resolveHubByWebUrl(written)).toBe(HUBS.local);
    }
    expect(resolveHubByWebUrl("https://calkit.io/")).toBe(HUBS.production);
  });

  test("derives a hub it doesn't know", () => {
    const hub = resolveHubByWebUrl("calkit.example.edu");
    expect(hub.apiUrl).toBe("https://api.calkit.example.edu");
    expect(hub.webUrl).toBe("https://calkit.example.edu");
  });
});

describe("getHub", () => {
  test("resolves built-ins and falls back for anything else", () => {
    expect(getHub("local").apiUrl).toBe("http://api.localhost");
    // An instance that isn't built in has no host permission, so falling
    // back beats leaving the extension with an API URL it can't reach
    expect(getHub("nonexistent")).toBe(HUBS.production);
  });
});

describe("resolveHubByWebUrl", () => {
  test("names a hub it doesn't know, and says it doesn't know it", () => {
    // A project can declare any hub; this build can only reach the ones
    // it ships a host permission for, which is why joining means adding
    // an entry to HUBS
    const known = resolveHubByWebUrl("https://calkit.io");
    expect(known).toBe(HUBS.production);
    expect(isKnownHub(known)).toBe(true);
    const other = resolveHubByWebUrl("calkit.example.edu");
    expect(other.label).toBe("calkit.example.edu");
    expect(other.apiUrl).toBe("https://api.calkit.example.edu");
    expect(isKnownHub(other)).toBe(false);
  });
});

describe("visibleHubs", () => {
  const names = (email: string | null, current = "production") =>
    visibleHubs(email, current).map((hub) => hub.name);

  test("offers staging only to the people who work on Calkit", () => {
    expect(names("petebachant@gmail.com")).toContain("staging");
    expect(names("PeteBachant@Gmail.com")).toContain("staging");
    expect(names("someone@university.edu")).not.toContain("staging");
    expect(names(null)).not.toContain("staging");
  });

  test("keeps the hub in use listed even when it wouldn't be offered", () => {
    // Otherwise someone already on staging gets a picker that can't
    // represent where they are
    expect(names("someone@university.edu", "staging")).toContain("staging");
  });

  test("leaves the other hubs alone", () => {
    expect(names(null)).toContain("production");
    expect(names(null)).toContain("local");
  });
});

describe("isLoopbackHost", () => {
  test("covers the names a local development stack answers on", () => {
    expect(isLoopbackHost("localhost")).toBe(true);
    // Object storage answers on its own subdomain, so the artifact URL
    // isn't the hub's host
    expect(isLoopbackHost("objects.localhost")).toBe(true);
    expect(isLoopbackHost("api.localhost")).toBe(true);
    expect(isLoopbackHost("127.0.0.1")).toBe(true);
    expect(isLoopbackHost("127.1.2.3")).toBe(true);
    expect(isLoopbackHost("[::1]")).toBe(true);
    expect(isLoopbackHost("LOCALHOST")).toBe(true);
  });

  test("doesn't mistake a lookalike for this machine", () => {
    expect(isLoopbackHost("localhost.example.com")).toBe(false);
    expect(isLoopbackHost("notlocalhost")).toBe(false);
    expect(isLoopbackHost("calkit.io")).toBe(false);
    expect(isLoopbackHost("127.0.0.1.example.com")).toBe(false);
  });
});
