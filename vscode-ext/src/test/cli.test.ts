import assert from "node:assert/strict";
import * as path from "node:path";
import test from "node:test";
import { isAppControlBlock, missingInstallDirs } from "../cli";

test("missingInstallDirs finds install folders missing from PATH", () => {
  const home = "/home/me";
  const local = path.join(home, ".local", "bin");
  const pixi = path.join(home, ".pixi", "bin");
  const at =
    (...dirs: string[]) =>
    (p: string) =>
      dirs.includes(p);
  // VS Code started without the shell's PATH: uv's and pixi's folders, and
  // Homebrew's and MacTeX's on a Mac
  assert.deepEqual(
    missingInstallDirs(
      { PATH: "/usr/bin:/bin" },
      home,
      "darwin",
      at(local, pixi, "/opt/homebrew/bin", "/Library/TeX/texbin"),
    ),
    [local, pixi, "/opt/homebrew/bin", "/Library/TeX/texbin"],
  );
  // Nothing to add when PATH already has them, or they don't exist
  assert.deepEqual(
    missingInstallDirs(
      { PATH: `/usr/bin:${local}` },
      home,
      "darwin",
      at(local),
    ),
    [],
  );
  assert.deepEqual(
    missingInstallDirs({ PATH: "/usr/bin" }, home, "darwin", at()),
    [],
  );
  // Folders set by environment variables, an unset PATH, and nothing
  // Mac-only elsewhere
  const pixiHome = path.join("/px", "bin");
  assert.deepEqual(
    missingInstallDirs(
      { UV_TOOL_BIN_DIR: "/tools", PIXI_HOME: "/px" },
      home,
      "linux",
      at("/tools", pixiHome, "/opt/homebrew/bin"),
    ),
    ["/tools", pixiHome],
  );
  // The same folder named twice is added once
  assert.deepEqual(
    missingInstallDirs(
      { PATH: "/usr/bin", XDG_BIN_HOME: local },
      home,
      "linux",
      at(local),
    ),
    [local],
  );
  // Windows separates PATH with semicolons
  assert.deepEqual(
    missingInstallDirs(
      { PATH: `C:\\Windows;${local}` },
      home,
      "win32",
      at(local),
    ),
    [],
  );
});

test("isAppControlBlock tells Windows blocking the CLI from it missing", () => {
  const blocked = [
    // Windows refused to start calkit.exe
    Object.assign(new Error("spawn calkit UNKNOWN"), { code: "UNKNOWN" }),
    // It started, but a DLL was blocked, as an unsigned or signed status
    Object.assign(new Error("Command failed"), { code: 0xc0e90002 }),
    Object.assign(new Error("Command failed"), { code: -1058471934 }),
    // uv's launcher couldn't start the Python it installed
    Object.assign(new Error("Command failed: calkit --version"), {
      code: 1,
      stderr:
        "Failed to spawn: An Application Control policy has blocked this file. (os error 4551)",
    }),
  ];
  for (const error of blocked) {
    assert.equal(isAppControlBlock(error, "win32"), true);
    // Nothing on other platforms is blocked this way
    assert.equal(isAppControlBlock(error, "linux"), false);
  }
  // Not installed, or failing for some other reason
  const notBlocked = [
    Object.assign(new Error("spawn calkit ENOENT"), { code: "ENOENT" }),
    Object.assign(new Error("Command failed"), { code: 1, stderr: "Error" }),
    Object.assign(new Error("timed out"), { killed: true, signal: "SIGTERM" }),
    "failed",
    undefined,
  ];
  for (const error of notBlocked) {
    assert.equal(isAppControlBlock(error, "win32"), false);
  }
});
