import assert from "node:assert/strict";
import * as path from "node:path";
import test from "node:test";
import { pathWithInstallDirs } from "../cli";

test("pathWithInstallDirs adds install folders missing from PATH", () => {
  const home = "/home/me";
  const local = path.join(home, ".local", "bin");
  const pixi = path.join(home, ".pixi", "bin");
  const at =
    (...dirs: string[]) =>
    (p: string) =>
      dirs.includes(p);
  // VS Code started without the shell's PATH: uv's and pixi's folders, and
  // Homebrew's on a Mac
  assert.equal(
    pathWithInstallDirs(
      { PATH: "/usr/bin:/bin" },
      home,
      "darwin",
      at(local, pixi, "/opt/homebrew/bin"),
    ),
    `/usr/bin:/bin:${local}:${pixi}:/opt/homebrew/bin`,
  );
  // Nothing to add when PATH already has them, or they don't exist
  assert.equal(
    pathWithInstallDirs(
      { PATH: `/usr/bin:${local}` },
      home,
      "darwin",
      at(local),
    ),
    undefined,
  );
  assert.equal(
    pathWithInstallDirs({ PATH: "/usr/bin" }, home, "darwin", at()),
    undefined,
  );
  // Folders set by environment variables, and no Homebrew off a Mac
  assert.equal(
    pathWithInstallDirs(
      { PATH: "/usr/bin", UV_TOOL_BIN_DIR: "/tools", PIXI_HOME: "/px" },
      home,
      "linux",
      at("/tools", "/px/bin", "/opt/homebrew/bin"),
    ),
    "/usr/bin:/tools:/px/bin",
  );
  // Windows separates PATH with semicolons
  assert.equal(
    pathWithInstallDirs({ PATH: "C:\\Windows" }, home, "win32", at(local)),
    `C:\\Windows;${local}`,
  );
});
