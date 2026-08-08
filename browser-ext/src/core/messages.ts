import type { AuthState } from "./auth";
import type { Hub } from "./hubs";
import type { SettingsUpdate, SettingsView } from "./storage";
import type {
  CalkitYamlInfo,
  ContentsItem,
  Figure,
  OverleafLinkPublic,
  OverleafLookup,
  OverleafSyncResponse,
  OverleafSyncStatus,
  ProjectPublic,
  ProjectsPublic,
  ReferenceNote,
  ReferenceSearchMatch,
  References,
} from "./types";

/**
 * A hub other than the configured one, named by its web URL.
 *
 * A project declares the hub it belongs to, so a surface that has read
 * that declaration can work with the project where it actually lives
 * without changing which hub the extension uses by default.
 */
export interface HubScoped {
  hubUrl?: string;
}

/**
 * Every operation a UI surface can ask the service worker to perform.
 *
 * These are named operations rather than a general "call this URL" proxy so a
 * content script can only do what the extension actually needs, and the token
 * stays in the service worker.
 */
export type Request =
  | ({ type: "auth.state" } & HubScoped)
  | ({ type: "auth.signIn" } & HubScoped)
  | { type: "auth.signOut" }
  | { type: "settings.get" }
  | { type: "settings.set"; update: SettingsUpdate }
  | { type: "hubs.get" }
  | {
      type: "projects.list";
      searchFor?: string;
      limit?: number;
      /**
       * Defaults to write, since every surface here either writes to a
       * project or offers to. Listing projects the user can only read
       * would put other people's projects in a picker whose actions
       * would then fail.
       */
      minAccessLevel?: "read" | "write";
    }
  | ({ type: "projects.byGithubRepo"; githubRepo: string } & HubScoped)
  | ({
      type: "projects.create";
      name: string;
      title: string;
      gitRepoUrl: string;
      isPublic: boolean;
    } & HubScoped)
  | { type: "github.calkitInfo"; githubRepo: string }
  | ({
      type: "project.contents";
      owner: string;
      project: string;
      path?: string;
    } & HubScoped)
  | { type: "project.figures"; owner: string; project: string }
  | { type: "content.imageDataUrl"; url: string }
  | { type: "overleaf.links"; overleafProjectId: string }
  | {
      type: "overleaf.lookup";
      overleafProjectId: string;
      /** Searched first, being where the document most likely belongs. */
      activeProject?: string;
      refresh?: boolean;
    }
  | {
      type: "overleaf.status";
      owner: string;
      project: string;
      overleafProjectId?: string;
      path?: string;
    }
  | { type: "overleaf.sync"; owner: string; project: string; path: string }
  | {
      type: "overleaf.import";
      owner: string;
      project: string;
      overleafProjectUrl: string;
      path: string;
      kind: string;
      title?: string;
    }
  | { type: "references.list"; owner: string; project: string }
  | {
      type: "references.search";
      projects: string[];
      doi?: string;
      arxivId?: string;
      title?: string;
    }
  | {
      type: "references.add";
      owner: string;
      project: string;
      path: string;
      key: string;
      entryType: string;
      fields: Record<string, string>;
    }
  | {
      type: "references.notes.get";
      owner: string;
      project: string;
      path: string;
      bibKey: string;
    }
  | {
      type: "references.notes.put";
      owner: string;
      project: string;
      path: string;
      bibKey: string;
      notes: ReferenceNote[];
    };

export interface ResponseMap {
  "auth.state": AuthState;
  "auth.signIn": AuthState;
  "auth.signOut": AuthState;
  "settings.get": SettingsView;
  "settings.set": SettingsView;
  "hubs.get": { hubs: Hub[]; current: Hub };
  "projects.list": ProjectsPublic;
  "projects.byGithubRepo": ProjectsPublic;
  "projects.create": ProjectPublic;
  "github.calkitInfo": CalkitYamlInfo;
  "project.contents": ContentsItem;
  "project.figures": Figure[];
  "content.imageDataUrl": string;
  "overleaf.links": OverleafLinkPublic[];
  "overleaf.lookup": OverleafLookup;
  "overleaf.status": OverleafSyncStatus[];
  "overleaf.sync": OverleafSyncResponse;
  "overleaf.import": { path: string; title: string };
  "references.list": References[];
  "references.search": ReferenceSearchMatch[];
  "references.add": { message: string };
  "references.notes.get": { notes: ReferenceNote[] };
  "references.notes.put": { notes: ReferenceNote[] };
}

/**
 * Sent from the service worker to a tab when its URL changes.
 *
 * GitHub and Overleaf are single-page apps, so the URL changes without a
 * document load. The service worker already hears about that through
 * chrome.tabs.onUpdated, which is why no content script has to poll for it.
 */
export interface UrlChanged {
  type: "url.changed";
  url: string;
}

/**
 * Whether this script can still reach the extension it was injected by.
 *
 * Reloading or updating an extension does not remove the content scripts it
 * already injected: they keep running in the page with their listeners and
 * handlers intact, but their connection to the extension is gone for good.
 * Every message such an orphan sends rejects, so anything that talks to the
 * service worker has to check first.
 */
export function isExtensionAlive(): boolean {
  try {
    return Boolean(chrome.runtime?.id);
  } catch {
    // Touching chrome.runtime can itself throw once the context is gone
    return false;
  }
}

/** Raised instead of messaging when the extension has been reloaded. */
export class ExtensionReloaded extends Error {
  constructor() {
    super("The Calkit extension was reloaded; refresh this page");
    this.name = "ExtensionReloaded";
  }
}

/**
 * Run a callback whenever the tab navigates, including within an SPA.
 *
 * Returns a function that stops listening, which a content script calls
 * when it finds itself orphaned so a dead copy goes quiet.
 */
export function onUrlChange(callback: (url: string) => void): () => void {
  const listener = (message: UrlChanged) => {
    if (message?.type === "url.changed") {
      callback(message.url);
    }
    return false;
  };
  try {
    chrome.runtime.onMessage.addListener(listener);
  } catch {
    return () => undefined;
  }
  return () => {
    try {
      chrome.runtime.onMessage.removeListener(listener);
    } catch {
      // Already gone with the context
    }
  };
}

export type Envelope<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; notSignedIn?: boolean };

export class RequestFailed extends Error {
  readonly notSignedIn: boolean;

  constructor(message: string, notSignedIn: boolean) {
    super(message);
    this.name = "RequestFailed";
    this.notSignedIn = notSignedIn;
  }
}

/** Ask the service worker to run an operation, from any UI surface. */
export async function send<K extends Request["type"]>(
  request: Extract<Request, { type: K }>,
): Promise<ResponseMap[K]> {
  // Checking first turns an endless stream of unhandled rejections from an
  // orphaned content script into one error its caller can act on
  if (!isExtensionAlive()) {
    throw new ExtensionReloaded();
  }
  const envelope = (await chrome.runtime.sendMessage(request)) as Envelope<
    ResponseMap[K]
  >;
  if (!envelope) {
    throw new RequestFailed("No response from the Calkit extension", false);
  }
  if (!envelope.ok) {
    throw new RequestFailed(envelope.error, Boolean(envelope.notSignedIn));
  }
  return envelope.data;
}
