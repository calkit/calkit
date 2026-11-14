/**
 * Calkit on this computer, which the browser starts when the extension
 * connects to it, so the extension can work with projects here directly
 * rather than through a hub. See calkit/browser_link.py.
 *
 * It needs the optional nativeMessaging permission, asked for from the
 * options page, and 'calkit browser-link install', which the installer runs.
 */

export const HOST_NAME = "io.calkit.native";

/** How long the host is kept running once nothing's waiting on it. */
const IDLE_MS = 5 * 60 * 1000;
const TIMEOUT_MS = 60 * 1000;

export interface LocalStatus {
  /** Whether the extension may start Calkit here. */
  permitted: boolean;
  /**
   * Whether the permission was granted after the background started, which
   * Chrome only gives the API to once the extension reloads.
   */
  needsReload?: boolean;
  /** Calkit's version here, if it answered. */
  version?: string;
  /** The editor projects open in, e.g., "vscode". */
  editor?: string;
  error?: string;
}

/** What's in a checkout that isn't saved or synced, from calkit/browser_link.py. */
export interface CheckoutStatus {
  path: string;
  branch: string | null;
  /** Changed, staged, or new, up to 50 of them. */
  unsaved_files: string[];
  n_unsaved_files: number;
  commits_ahead: number;
  overleaf: {
    /** The folder synced with Overleaf. */
    path: string;
    files_to_push?: string[];
    n_files_to_push?: number;
    n_files_to_delete?: number;
    syncing?: boolean;
    /** Not synced from this checkout, e.g., since the hub syncs it. */
    never_synced?: boolean;
    error?: string;
  }[];
}

interface Pending {
  resolve: (value: unknown) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

let port: chrome.runtime.Port | null = null;
let nextId = 1;
let idleTimer: ReturnType<typeof setTimeout> | undefined;
const pending = new Map<number, Pending>();

export async function isLocalPermitted(): Promise<boolean> {
  return chrome.permissions.contains({ permissions: ["nativeMessaging"] });
}

/** What the browser's error means for someone who can fix it. */
export function describeHostError(message: string): string {
  if (/not found/i.test(message)) {
    return (
      "Calkit isn't set up for the browser on this computer; install it, " +
      "or run 'calkit browser-link install'"
    );
  }
  if (/forbidden/i.test(message)) {
    return (
      "Calkit on this computer doesn't allow this extension; run " +
      "'calkit browser-link install'"
    );
  }
  if (/exited/i.test(message)) {
    return "Calkit on this computer stopped unexpectedly";
  }
  return message;
}

function getPort(): chrome.runtime.Port {
  if (port) {
    return port;
  }
  const p = chrome.runtime.connectNative(HOST_NAME);
  p.onMessage.addListener((msg: { id?: number; ok?: boolean }) => {
    const waiting = msg.id === undefined ? undefined : pending.get(msg.id);
    if (!waiting) {
      return;
    }
    pending.delete(msg.id as number);
    clearTimeout(waiting.timer);
    if (msg.ok) {
      waiting.resolve((msg as { result: unknown }).result);
    } else {
      waiting.reject(new Error((msg as { error?: string }).error ?? "Failed"));
    }
    keepAliveUntilIdle();
  });
  p.onDisconnect.addListener(() => {
    const error = describeHostError(
      chrome.runtime.lastError?.message ?? "Calkit on this computer closed",
    );
    if (port === p) {
      port = null;
    }
    for (const [id, waiting] of pending) {
      clearTimeout(waiting.timer);
      waiting.reject(new Error(error));
      pending.delete(id);
    }
  });
  port = p;
  return p;
}

/** Stop the host once nothing's been asked of it for a while. */
function keepAliveUntilIdle(): void {
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    if (pending.size === 0 && port) {
      port.disconnect();
      port = null;
    }
  }, IDLE_MS);
}

/** Ask Calkit on this computer something, starting it if need be. */
export async function askLocal<T>(
  request: { type: string } & Record<string, unknown>,
): Promise<T> {
  if (!(await isLocalPermitted())) {
    throw new Error(
      "The extension isn't allowed to reach Calkit on this computer; " +
        "connect it from the extension's options",
    );
  }
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("Calkit on this computer didn't answer"));
    }, TIMEOUT_MS);
    pending.set(id, {
      resolve: resolve as (value: unknown) => void,
      reject,
      timer,
    });
    try {
      getPort().postMessage({ ...request, id });
    } catch (e) {
      clearTimeout(timer);
      pending.delete(id);
      reject(e instanceof Error ? e : new Error(String(e)));
    }
    keepAliveUntilIdle();
  });
}

/** Whether Calkit on this computer can be reached, and its version. */
export async function getLocalStatus(): Promise<LocalStatus> {
  if (!(await isLocalPermitted())) {
    return { permitted: false };
  }
  if (typeof chrome.runtime.connectNative !== "function") {
    return { permitted: true, needsReload: true };
  }
  try {
    const { version, editor } = await askLocal<{
      version: string;
      editor?: string;
    }>({ type: "ping" });
    return { permitted: true, version, editor };
  } catch (e) {
    return {
      permitted: true,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

/** The editor's name, as a button would say it. */
export function getEditorLabel(editor: string | undefined): string {
  const names: Record<string, string> = {
    vscode: "VS Code",
    code: "VS Code",
    cursor: "Cursor",
    vscodium: "VSCodium",
    codium: "VSCodium",
    positron: "Positron",
    antigravity: "Antigravity",
    windsurf: "Windsurf",
    jupyterlab: "JupyterLab",
  };
  const command = editor?.split(" ")[0] ?? "";
  return names[editor ?? ""] ?? names[command] ?? "your editor";
}
