import { describe, expect, test } from "vitest";

import { hubUrlFromCalkitYaml } from "./calkit-yaml";
import { HUBS } from "./hubs";

describe("hubUrlFromCalkitYaml", () => {
  test("a file naming no hub means calkit.io", () => {
    // A project only records its hub when it isn't calkit.io, so a file
    // without the key must not inherit whichever hub the reader is using
    expect(hubUrlFromCalkitYaml("title: A project\n")).toBe(
      HUBS.production.webUrl,
    );
    expect(hubUrlFromCalkitYaml("")).toBe(HUBS.production.webUrl);
  });

  test("reads a declared hub", () => {
    expect(hubUrlFromCalkitYaml("hub: http://localhost:5173\n")).toBe(
      "http://localhost:5173",
    );
    expect(
      hubUrlFromCalkitYaml(
        'title: A project\nhub: "https://calkit.example.edu"\n',
      ),
    ).toBe("https://calkit.example.edu");
    // Quotes, trailing slashes, and trailing comments don't survive
    expect(
      hubUrlFromCalkitYaml("hub: 'https://calkit.example.edu/' # ours\n"),
    ).toBe("https://calkit.example.edu");
  });

  test("normalises a hub written without a scheme", () => {
    // Otherwise a hand-written calkit.yaml resolves to a different hub
    // than one the CLI wrote, and credentials are stored per hub
    expect(hubUrlFromCalkitYaml("hub: localhost:5173\n")).toBe(
      "http://localhost:5173",
    );
    expect(hubUrlFromCalkitYaml("hub: calkit.example.edu\n")).toBe(
      "https://calkit.example.edu",
    );
  });

  test("ignores a hub key that isn't top level", () => {
    // Nested keys belong to something else, e.g. an entry that happens to
    // carry its own hub field
    expect(
      hubUrlFromCalkitYaml("environments:\n  x:\n    hub: http://nope\n"),
    ).toBe(HUBS.production.webUrl);
  });
});
