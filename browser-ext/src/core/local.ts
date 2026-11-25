/**
 * Calkit on this machine, which the browser starts when the extension
 * connects to it, so the extension can work with projects here directly
 * rather than through a hub. See calkit/browser_link.py.
 *
 * It needs the optional nativeMessaging permission, asked for from the
 * options page, and 'calkit browser-link install', which the installer runs.
 */
import { type Synctex, parseSynctex } from "../../../vscode-ext/src/latex/pdf";

import type { RunProgress } from "./types";

export const HOST_NAME = "io.calkit.native";

/** How long the host is kept running once nothing's waiting on it. */
const IDLE_MS = 5 * 60 * 1000;
const TIMEOUT_MS = 60 * 1000;
/**
 * How long Calkit answering here is trusted, so each request routed here
 * doesn't ask first.
 */
const STATUS_TTL_MS = 30 * 1000;

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
  /** Whether it's installed, or else it can be. */
  editorInstalled?: boolean;
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
let knownStatus: { at: number; status: Promise<LocalStatus> } | null = null;

export async function isLocalPermitted(): Promise<boolean> {
  return chrome.permissions.contains({ permissions: ["nativeMessaging"] });
}

/** What the browser's error means for someone who can fix it. */
export function describeHostError(message: string): string {
  if (/not found/i.test(message)) {
    return (
      "Calkit isn't set up for the browser on this machine; install it, " +
      "or run 'calkit browser-link install'"
    );
  }
  if (/forbidden/i.test(message)) {
    return (
      "Calkit on this machine doesn't allow this extension; run " +
      "'calkit browser-link install'"
    );
  }
  if (/exited/i.test(message)) {
    return "Calkit on this machine stopped unexpectedly";
  }
  return message;
}

/** A request Calkit here refused, with the hub's status for the same. */
export class LocalError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "LocalError";
    this.status = status;
  }
}

/**
 * A job Calkit here runs in a process of its own, e.g., a pipeline run,
 * from calkit/browser_link.py.
 */
export interface LocalJob {
  id: string;
  kind:
    | "run"
    | "sync"
    | "save"
    | "clone"
    | "create"
    | "install-editor"
    | "detect";
  project: string;
  wdir: string;
  status: "queued" | "running" | "succeeded" | "failed";
  created: string;
  started: string | null;
  finished: string | null;
  git_rev: string | null;
  branch: string | null;
  /** The end of what it's printed, as it runs and once it's done. */
  output: string | null;
  /** What it's doing, while it runs. */
  progress?: RunProgress;
  /** What each of its commands does, for one with several, e.g., a create. */
  steps?: string[] | null;
  /** Which of them is running, or the last that ran. */
  step?: number;
  error: string | null;
  /** The hub's status for the same failure, e.g., 401 for credentials. */
  error_status?: number;
  result: Record<string, unknown> | null;
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
      const { error, status } = msg as { error?: string; status?: number };
      waiting.reject(new LocalError(error ?? "Failed", status));
    }
    keepAliveUntilIdle();
  });
  p.onDisconnect.addListener(() => {
    const error = describeHostError(
      chrome.runtime.lastError?.message ?? "Calkit on this machine closed",
    );
    if (port === p) {
      port = null;
      knownStatus = null;
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

/** Ask Calkit on this machine something, starting it if need be. */
export async function askLocal<T>(
  request: { type: string } & Record<string, unknown>,
  timeoutMs = TIMEOUT_MS,
): Promise<T> {
  if (!(await isLocalPermitted())) {
    throw new Error(
      "The extension isn't allowed to reach Calkit on this machine; " +
        "connect it from the extension's options",
    );
  }
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error("Calkit on this machine didn't answer"));
    }, timeoutMs);
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

/**
 * Whether Calkit on this machine can be reached, and its version, as it
 * last said within ``STATUS_TTL_MS``.
 */
export async function getLocalStatus(): Promise<LocalStatus> {
  if (!(await isLocalPermitted())) {
    return { permitted: false };
  }
  if (typeof chrome.runtime.connectNative !== "function") {
    return { permitted: true, needsReload: true };
  }
  if (knownStatus && Date.now() - knownStatus.at < STATUS_TTL_MS) {
    return knownStatus.status;
  }
  const status = (async (): Promise<LocalStatus> => {
    try {
      const reply = await askLocal<{
        version: string;
        editor?: string;
        editor_installed?: boolean;
      }>({ type: "ping" });
      return {
        permitted: true,
        version: reply.version,
        editor: reply.editor,
        editorInstalled: reply.editor_installed,
      };
    } catch (e) {
      return {
        permitted: true,
        error: e instanceof Error ? e.message : String(e),
      };
    }
  })();
  knownStatus = { at: Date.now(), status };
  // Only an answer is kept, so a failure's asked about again
  void status.then((s) => {
    if (!s.version && knownStatus?.status === status) {
      knownStatus = null;
    }
  });
  return status;
}

/** Ask again next time, e.g., once an editor's been installed. */
export function forgetLocalStatus(): void {
  knownStatus = null;
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

/** A part of a PDF read from this machine, with how fresh it is. */
export interface LocalPdfChunk {
  path: string;
  size: number;
  offset: number;
  /** Base64. */
  data: string;
  /** With the first part only. */
  built?: number;
  commit_sha?: string | null;
  changed_since_commit?: boolean | null;
  edited_since_built?: boolean;
}

/**
 * The PDF a folder synced with Overleaf builds to on this machine, read a
 * part at a time, since a message to or from Calkit here can't be over
 * 1 MB, with the first part, which says how fresh it is.
 */
export async function getLocalPdf(
  project: string,
  folder: string,
  type: "publication.pdf" | "publication.synctex" = "publication.pdf",
): Promise<{ parts: Uint8Array[]; first: LocalPdfChunk }> {
  const parts: Uint8Array[] = [];
  let first: LocalPdfChunk | null = null;
  let offset = 0;
  do {
    const chunk: LocalPdfChunk = await askLocal({
      type,
      project,
      folder,
      offset,
    });
    first ??= chunk;
    const bytes = Uint8Array.from(atob(chunk.data), (c) => c.charCodeAt(0));
    parts.push(bytes);
    offset += bytes.length;
    if (!bytes.length) {
      break;
    }
  } while (offset < first.size);
  return { parts, first };
}

/**
 * The SyncTeX the PDF a folder builds to on this machine was built with,
 * which says where in the source each place in it came from, or null if
 * there isn't any.
 */
export async function getLocalSynctex(
  project: string,
  folder: string,
): Promise<Synctex | null> {
  const text = await getLocalSynctexText(project, folder);
  return text === null ? null : parseSynctex(text);
}

/** The text of that SyncTeX file, uncompressed, or null. */
export async function getLocalSynctexText(
  project: string,
  folder: string,
): Promise<string | null> {
  try {
    const { parts } = await getLocalPdf(project, folder, "publication.synctex");
    return await new Response(
      new Blob(parts as BlobPart[])
        .stream()
        .pipeThrough(new DecompressionStream("gzip")),
    ).text();
  } catch {
    return null;
  }
}

/** The hash Git gives a file with these contents, as Overleaf's are given. */
export async function getGitBlobSha(data: Uint8Array): Promise<string> {
  const header = new TextEncoder().encode(`blob ${data.length}\0`);
  const blob = new Uint8Array(header.length + data.length);
  blob.set(header);
  blob.set(data, header.length);
  const digest = await crypto.subtle.digest("SHA-1", blob);
  return [...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
