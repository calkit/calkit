import * as fs from "node:fs";
import * as path from "node:path";

// Where installers put the commands the extension and Calkit run: uv's tool
// folder, where calkit goes, pixi's, and Homebrew's on Apple silicon
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
    dirs.push("/opt/homebrew/bin");
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

// PATH with the install folders that exist but are missing from it, or
// undefined if none are. VS Code doesn't always pass on the shell's PATH,
// e.g., when started from the desktop, so `calkit` alone isn't found.
export function pathWithInstallDirs(
  env: Record<string, string | undefined>,
  home: string,
  platform: string,
  exists: (p: string) => boolean = isDir,
): string | undefined {
  const sep = platform === "win32" ? ";" : ":";
  const dirs = (env.PATH ?? "").split(sep).filter(Boolean);
  const missing = [
    ...new Set(installDirs(env, home, platform).filter(exists)),
  ].filter((dir) => !dirs.includes(dir));
  return missing.length ? [...dirs, ...missing].join(sep) : undefined;
}
