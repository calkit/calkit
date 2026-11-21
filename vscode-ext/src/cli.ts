import * as fs from "node:fs";
import * as path from "node:path";

// Where installers put the commands the extension and Calkit run: uv's tool
// folder, where calkit goes, pixi's, and on a Mac, Homebrew's on Apple silicon
// and MacTeX's, which only a login shell adds from /etc/paths.d
export function installDirs(
  env: Record<string, string | undefined>,
  home: string,
  platform: string,
): string[] {
  const dirs = [
    env.UV_TOOL_BIN_DIR,
    env.XDG_BIN_HOME,
    path.join(home, ".local", "bin"),
    env.PIXI_HOME ? path.join(env.PIXI_HOME, "bin") : undefined,
    path.join(home, ".pixi", "bin"),
  ];
  if (platform === "darwin") {
    dirs.push("/opt/homebrew/bin", "/Library/TeX/texbin");
  }
  return dirs.filter((dir): dir is string => !!dir);
}

function isDir(p: string): boolean {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

// Install folders that exist but are missing from PATH. VS Code doesn't
// always pass on the shell's PATH, e.g., when started from the desktop, so
// `calkit` alone isn't found.
export function missingInstallDirs(
  env: Record<string, string | undefined>,
  home: string,
  platform: string,
  exists: (p: string) => boolean = isDir,
): string[] {
  const dirs = (env.PATH ?? "").split(platform === "win32" ? ";" : ":");
  return [...new Set(installDirs(env, home, platform))].filter(
    (dir) => !dirs.includes(dir) && exists(dir),
  );
}

// STATUS_SYSTEM_INTEGRITY_POLICY_VIOLATION, what a process exits with when
// Windows won't load one of its DLLs
const APP_CONTROL_BLOCK_STATUS = 0xc0e90002;
const APP_CONTROL_BLOCK_REGEX =
  /Application Control policy has blocked|os error 4551|0xc0e90002/i;

// Whether running a command failed because Windows App Control, e.g., Smart
// App Control, blocked an unsigned file it doesn't trust, like the calkit.exe
// uv installs or the Python it starts. Windows refusing to start a program
// has no error code of its own in Node, so shows as UNKNOWN.
export function isAppControlBlock(error: unknown, platform: string): boolean {
  if (platform !== "win32" || typeof error !== "object" || error === null) {
    return false;
  }
  const { code, message, stderr } = error as {
    code?: unknown;
    message?: unknown;
    stderr?: unknown;
  };
  if (code === "UNKNOWN") {
    return true;
  }
  if (typeof code === "number" && code >>> 0 === APP_CONTROL_BLOCK_STATUS) {
    return true;
  }
  return APP_CONTROL_BLOCK_REGEX.test(`${message ?? ""}\n${stderr ?? ""}`);
}
