import type { AuthState } from "./auth";
import type { Hub } from "./hubs";
import type { Settings } from "./storage";
import type {
  ContentsItem,
  Figure,
  OverleafLinkPublic,
  OverleafSyncResponse,
  OverleafSyncStatus,
  ProjectsPublic,
  ReferenceNote,
  ReferenceSearchMatch,
  References,
  ZoteroCollection,
  ZoteroLibrary,
  ZoteroSyncResponse,
} from "./types";

/**
 * Every operation a UI surface can ask the service worker to perform.
 *
 * These are named operations rather than a general "call this URL" proxy so a
 * content script can only do what the extension actually needs, and the token
 * stays in the service worker.
 */
export type Request =
  | { type: "auth.state" }
  | { type: "auth.signIn" }
  | { type: "auth.signOut" }
  | { type: "settings.get" }
  | { type: "settings.set"; update: Partial<Settings> }
  | { type: "hubs.get" }
  | { type: "projects.list"; searchFor?: string; limit?: number }
  | { type: "projects.byGithubRepo"; githubRepo: string }
  | {
      type: "project.contents";
      owner: string;
      project: string;
      path?: string;
    }
  | { type: "project.figures"; owner: string; project: string }
  | { type: "content.imageDataUrl"; url: string }
  | { type: "overleaf.links"; overleafProjectId: string }
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
    }
  | { type: "zotero.libraries"; owner: string; project: string }
  | {
      type: "zotero.collections";
      owner: string;
      project: string;
      libraryType: "user" | "group";
      libraryId: string;
    }
  | {
      type: "zotero.import";
      owner: string;
      project: string;
      libraryType: "user" | "group";
      libraryId: string;
      collectionKey: string;
      bibPath: string;
    }
  | { type: "zotero.sync"; owner: string; project: string; path: string };

export interface ResponseMap {
  "auth.state": AuthState;
  "auth.signIn": AuthState;
  "auth.signOut": AuthState;
  "settings.get": Settings;
  "settings.set": Settings;
  "hubs.get": { hubs: Hub[]; current: Hub };
  "projects.list": ProjectsPublic;
  "projects.byGithubRepo": ProjectsPublic;
  "project.contents": ContentsItem;
  "project.figures": Figure[];
  "content.imageDataUrl": string;
  "overleaf.links": OverleafLinkPublic[];
  "overleaf.status": OverleafSyncStatus[];
  "overleaf.sync": OverleafSyncResponse;
  "overleaf.import": { path: string; title: string };
  "references.list": References[];
  "references.search": ReferenceSearchMatch[];
  "references.add": { message: string };
  "references.notes.get": { notes: ReferenceNote[] };
  "references.notes.put": { notes: ReferenceNote[] };
  "zotero.libraries": ZoteroLibrary[];
  "zotero.collections": ZoteroCollection[];
  "zotero.import": { path: string };
  "zotero.sync": ZoteroSyncResponse;
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
