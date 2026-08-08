import { describe, expect, test } from "vitest";

import { apiUrlFromHubUrl, customHubFromUrl, getHub, HUBS } from "./hubs";

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
