import { NotSignedInError, request } from "../core/api";
import { getAuthState, signIn, signOut } from "../core/auth";
import { HUBS } from "../core/hubs";
import type { Envelope, Request } from "../core/messages";
import { getCurrentHub, getSettingsView, setSettings } from "../core/storage";
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
} from "../core/types";

function projectPath(owner: string, project: string): string {
  return `/projects/${encodeURIComponent(owner)}/${encodeURIComponent(
    project,
  )}`;
}

const MAX_PREVIEW_BYTES = 2_000_000;

/**
 * Read an artifact into a data URL so a panel can preview it.
 *
 * A panel lives in the host page's DOM, so the page's own content security
 * policy governs what it may load, and sites like GitHub don't allow images
 * from object storage. Fetching here instead works because the extension's
 * host permissions aren't subject to the page's policy, and the data URL that
 * comes back is something the page's policy does allow.
 */
async function fetchImageDataUrl(url: string): Promise<string> {
  const parsed = new URL(url);
  if (parsed.protocol !== "https:") {
    throw new Error("Only https artifact URLs can be previewed");
  }
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Could not fetch artifact (${resp.status})`);
  }
  const blob = await resp.blob();
  if (!blob.type.startsWith("image/")) {
    throw new Error("Artifact is not an image");
  }
  if (blob.size > MAX_PREVIEW_BYTES) {
    throw new Error("Artifact is too large to preview");
  }
  const buffer = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (const byte of buffer) {
    binary += String.fromCharCode(byte);
  }
  return `data:${blob.type};base64,${btoa(binary)}`;
}

async function handle(message: Request): Promise<unknown> {
  switch (message.type) {
    case "auth.state":
      return getAuthState();
    case "auth.signIn":
      return signIn();
    case "auth.signOut":
      return signOut();
    case "settings.get":
      return getSettingsView();
    case "settings.set":
      return setSettings(message.update);
    case "hubs.get":
      return { hubs: Object.values(HUBS), current: await getCurrentHub() };
    case "projects.list":
      return request<ProjectsPublic>("/projects", {
        query: {
          search_for: message.searchFor,
          limit: message.limit ?? 100,
          min_access_level: message.minAccessLevel ?? "write",
        },
      });
    case "projects.byGithubRepo":
      // Read access on purpose, unlike the picker: browsing the DVC
      // artifacts behind a public repo you don't own is the point
      return request<ProjectsPublic>("/projects", {
        query: { github_repo: message.githubRepo },
      });
    case "project.contents":
      return request<ContentsItem>(
        `${projectPath(message.owner, message.project)}/contents`,
        { query: { path: message.path } },
      );
    case "project.figures":
      return request<Figure[]>(
        `${projectPath(message.owner, message.project)}/figures`,
      );
    case "content.imageDataUrl":
      return fetchImageDataUrl(message.url);
    case "overleaf.links":
      return request<OverleafLinkPublic[]>("/overleaf-links", {
        query: { overleaf_project_id: message.overleafProjectId },
      });
    case "overleaf.status":
      return request<OverleafSyncStatus[]>(
        `${projectPath(message.owner, message.project)}/overleaf-syncs/status`,
        {
          query: {
            overleaf_project_id: message.overleafProjectId,
            path: message.path,
          },
        },
      );
    case "overleaf.sync":
      return request<OverleafSyncResponse>(
        `${projectPath(message.owner, message.project)}/overleaf-syncs`,
        { method: "POST", body: { path: message.path } },
      );
    case "overleaf.import":
      return request<{ path: string; title: string }>(
        `${projectPath(message.owner, message.project)}/publications/overleaf`,
        {
          method: "POST",
          form: {
            path: message.path,
            kind: message.kind,
            overleaf_project_url: message.overleafProjectUrl,
            ...(message.title ? { title: message.title } : {}),
          },
        },
      );
    case "references.list":
      return request<References[]>(
        `${projectPath(message.owner, message.project)}/references`,
      );
    case "references.search":
      return request<ReferenceSearchMatch[]>("/user/references/search", {
        query: {
          projects: message.projects,
          doi: message.doi,
          arxiv_id: message.arxivId,
          title: message.title,
        },
      });
    case "references.add":
      return request<{ message: string }>(
        `${projectPath(message.owner, message.project)}/references/items`,
        {
          method: "POST",
          body: {
            path: message.path,
            key: message.key,
            type: message.entryType,
            fields: message.fields,
          },
        },
      );
    case "references.notes.get":
      return request<{ notes: ReferenceNote[] }>(
        `${projectPath(message.owner, message.project)}/references/items/` +
          `${encodeURIComponent(message.bibKey)}/notes`,
        { query: { path: message.path } },
      );
    case "references.notes.put":
      return request<{ notes: ReferenceNote[] }>(
        `${projectPath(message.owner, message.project)}/references/items/` +
          `${encodeURIComponent(message.bibKey)}/notes`,
        {
          method: "PUT",
          body: { path: message.path, notes: message.notes },
        },
      );
    case "zotero.libraries":
      return request<ZoteroLibrary[]>(
        `${projectPath(message.owner, message.project)}/zotero/libraries`,
      );
    case "zotero.collections":
      return request<ZoteroCollection[]>(
        `${projectPath(message.owner, message.project)}/zotero/collections`,
        {
          query: {
            library_type: message.libraryType,
            library_id: message.libraryId,
          },
        },
      );
    case "zotero.import":
      return request<{ path: string }>(
        `${projectPath(message.owner, message.project)}/zotero/imports`,
        {
          method: "POST",
          body: {
            library_type: message.libraryType,
            library_id: message.libraryId,
            collection_key: message.collectionKey,
            bib_path: message.bibPath,
          },
        },
      );
    case "zotero.sync":
      return request<ZoteroSyncResponse>(
        `${projectPath(message.owner, message.project)}/zotero/syncs`,
        { method: "POST", body: { path: message.path } },
      );
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only this extension's own pages and content scripts may drive the API.
  // Page scripts can't reach here (there's no externally_connectable), but
  // checking the sender keeps that guarantee explicit.
  if (sender.id !== chrome.runtime.id) {
    return false;
  }
  handle(message as Request)
    .then((data) => sendResponse({ ok: true, data } as Envelope<unknown>))
    .catch((e: unknown) => {
      const error = e instanceof Error ? e.message : String(e);
      sendResponse({
        ok: false,
        error,
        notSignedIn: e instanceof NotSignedInError,
      } as Envelope<unknown>);
    });
  // Keep the message channel open for the async response above
  return true;
});
