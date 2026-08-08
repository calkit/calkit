import { describe, expect, test } from "vitest";

import {
  apiUrlFromHubUrl,
  customHubFromUrl,
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

describe("customHubFromUrl", () => {
  test("builds a hub entry from just the web URL", () => {
    expect(customHubFromUrl("https://calkit.example.edu/")).toEqual({
      name: "custom",
      label: "calkit.example.edu",
      webUrl: "https://calkit.example.edu",
      apiUrl: "https://api.calkit.example.edu",
    });
    // A bare host gets a scheme on both URLs
    expect(customHubFromUrl("calkit.example.edu")).toEqual({
      name: "custom",
      label: "calkit.example.edu",
      webUrl: "https://calkit.example.edu",
      apiUrl: "https://api.calkit.example.edu",
    });
  });
});

describe("getHub", () => {
  test("resolves built-ins, the custom hub, and unknown names", () => {
    expect(getHub("local").apiUrl).toBe("http://api.localhost");
    const custom = customHubFromUrl("calkit.example.edu");
    expect(getHub("custom", custom)).toBe(custom);
    // A custom selection with nothing configured falls back rather than
    // leaving the extension with no API URL at all
    expect(getHub("custom", null)).toBe(HUBS.production);
    expect(getHub("nonexistent")).toBe(HUBS.production);
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
