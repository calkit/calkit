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
