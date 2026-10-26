import assert from "node:assert/strict";
import * as path from "node:path";
import test from "node:test";
import { missingInstallDirs } from "../cli";

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
