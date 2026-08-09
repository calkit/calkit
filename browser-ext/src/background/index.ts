import { ApiError, NotSignedInError, request } from "../core/api";
import { getAuthState, signIn, signOut } from "../core/auth";
import { hubUrlFromCalkitYaml } from "../core/calkit-yaml";
import {
  isLoopbackHost,
  resolveHubByWebUrl,
  visibleHubs,
  type Hub,
} from "../core/hubs";
import type { Envelope, Request } from "../core/messages";
import {
  getCurrentHub,
  getKnownEmail,
  getSettingsView,
  setSettings,
} from "../core/storage";
import type {
  CalkitYamlInfo,
  ContentsItem,
  DvcOutput,
  TextDiff,
  Figure,
  GithubRepo,
  OverleafLookup,
  OverleafSyncResponse,
  OverleafSyncStatus,
  ProjectPublic,
  ProjectsPublic,
  PullRequestRefs,
  ReferenceNote,
  ReferenceSearchMatch,
  References,
} from "../core/types";

function projectPath(owner: string, project: string): string {
  return `/projects/${encodeURIComponent(owner)}/${encodeURIComponent(
    project,
  )}`;
}

const MAX_PREVIEW_BYTES = 2_000_000;
const MAX_VIEWER_BYTES = 25_000_000;

/**
 * Read an artifact into a data URL so a panel can preview it.
 *
 * A panel lives in the host page's DOM, so the page's own content security
 * policy governs what it may load, and sites like GitHub don't allow images
 * from object storage. Fetching here instead works because the extension's
 * host permissions aren't subject to the page's policy, and the data URL that
 * comes back is something the page's policy does allow.
 */
async function fetchDataUrl(
  url: string,
  options: { imageOnly?: boolean; maxBytes?: number } = {},
): Promise<string> {
  const parsed = new URL(url);
  // Plain http only for this machine, where a development stack has no
  // certificates -- and where object storage answers on its own
  // subdomain, so the artifact URL isn't the hub's host
  if (
    parsed.protocol !== "https:" &&
    !(parsed.protocol === "http:" && isLoopbackHost(parsed.hostname))
  ) {
    throw new Error("Only https artifact URLs can be viewed");
  }
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`Could not fetch artifact (${resp.status})`);
  }
  const blob = await resp.blob();
  if (options.imageOnly && !blob.type.startsWith("image/")) {
    throw new Error("Artifact is not an image");
  }
  if (blob.size > (options.maxBytes ?? MAX_PREVIEW_BYTES)) {
    throw new Error("Artifact is too large to view here; download it instead");
  }
  const buffer = new Uint8Array(await blob.arrayBuffer());
  // In chunks, because appending a character at a time reallocates the
  // string on every byte -- fine for a thumbnail, minutes of a frozen
  // service worker for the 25 MB a PDF is allowed to be. The chunk stays
  // well under the argument limit String.fromCharCode has when spread.
  const CHUNK = 0x8000;
  const parts: string[] = [];
  for (let i = 0; i < buffer.length; i += CHUNK) {
    parts.push(String.fromCharCode(...buffer.subarray(i, i + CHUNK)));
  }
  return `data:${blob.type};base64,${btoa(parts.join(""))}`;
}

/**
 * Read a repo's calkit.yaml straight from GitHub to learn which hub it
 * belongs to.
 *
 * This asks the project itself rather than asking a hub whether it has
 * heard of the repo, so a project on some other instance is recognised
 * instead of looking like it isn't a Calkit project at all. Only public
 * repos answer; a private one 404s here and the hub lookup covers it.
 */
async function readCalkitYaml(githubRepo: string): Promise<CalkitYamlInfo> {
  const url = `https://raw.githubusercontent.com/${githubRepo}/HEAD/calkit.yaml`;
  let resp: Response;
  try {
    resp = await fetch(url);
  } catch {
    return { present: false, hubUrl: null };
  }
  if (!resp.ok) {
    return { present: false, hubUrl: null };
  }
  // Resolved here, so the rule that an absent key means calkit.io lives
  // next to the parsing rather than in each caller
  return { present: true, hubUrl: hubUrlFromCalkitYaml(await resp.text()) };
}

/** The hub a message names, or the configured one. */
function hubFor(message: { hubUrl?: string }): Hub | undefined {
  return message.hubUrl ? resolveHubByWebUrl(message.hubUrl) : undefined;
}

async function handle(message: Request): Promise<unknown> {
  switch (message.type) {
    case "auth.state":
      return getAuthState(hubFor(message));
    case "auth.signIn":
      return signIn(hubFor(message));
    case "auth.signOut":
      return signOut();
    case "settings.get":
      return getSettingsView();
    case "settings.set":
      return setSettings(message.update);
    case "hubs.get": {
      const current = await getCurrentHub();
      const settings = await getSettingsView();
      return {
        hubs: visibleHubs(
          await getKnownEmail(current.apiUrl),
          settings.hubName,
        ),
        current,
      };
    }
    case "projects.list":
      return request<ProjectsPublic>("/projects", {
        query: {
          search_for: message.searchFor,
          limit: message.limit ?? 100,
          min_access_level: message.minAccessLevel ?? "write",
        },
      });
    case "projects.create":
      return request<ProjectPublic>("/projects", {
        method: "POST",
        body: {
          name: message.name,
          title: message.title,
          // Null rather than empty: the hub reads null as "make me one"
          // and validates anything else as a github.com URL
          git_repo_url: message.gitRepoUrl || null,
          git_repo_exists: Boolean(message.gitRepoUrl),
          is_public: message.isPublic,
        },
        hub: hubFor(message),
      });
    case "github.repos":
      // The hub proxies this with the user's GitHub token, so the repos
      // offered are the ones they can actually attach a project to
      return request<GithubRepo[]>("/user/github/repos", {
        query: { per_page: message.perPage ?? 100 },
      });
    case "github.pullRequest":
      // Through the hub, which holds a GitHub token, so a private repo
      // resolves where an unauthenticated request would not
      return request<PullRequestRefs>(
        `${projectPath(message.owner, message.project)}/github-pulls/` +
          `${message.number}`,
        { hub: hubFor(message) },
      );
    case "github.calkitInfo":
      return readCalkitYaml(message.githubRepo);
    case "projects.byGithubRepo":
      // Read access on purpose, unlike the picker: browsing the DVC
      // artifacts behind a public repo you don't own is the point
      return request<ProjectsPublic>("/projects", {
        query: { github_repo: message.githubRepo },
        hub: hubFor(message),
      });
    case "project.contents":
      return request<ContentsItem>(
        `${projectPath(message.owner, message.project)}/contents`,
        {
          query: { path: message.path, ref: message.ref },
          hub: hubFor(message),
        },
      );
    case "project.dvcOutputs":
      return request<DvcOutput[]>(
        `${projectPath(message.owner, message.project)}/dvc-outputs`,
        { query: { ref: message.ref }, hub: hubFor(message) },
      );
    case "project.textDiff":
      return request<TextDiff>(
        `${projectPath(message.owner, message.project)}/dvc-outputs/text-diff`,
        {
          query: {
            path: message.path,
            base: message.base,
            head: message.head,
          },
          hub: hubFor(message),
        },
      );
    case "project.figures":
      return request<Figure[]>(
        `${projectPath(message.owner, message.project)}/figures`,
      );
    case "content.imageDataUrl":
      return fetchDataUrl(message.url, { imageOnly: true });
    case "content.dataUrl":
      // The viewer page shows PDFs and notebooks too, which run
      // larger than an inline preview ever would
      return fetchDataUrl(message.url, { maxBytes: MAX_VIEWER_BYTES });
    case "overleaf.lookup":
      return request<OverleafLookup>(
        `/user/overleaf-syncs/${encodeURIComponent(message.overleafProjectId)}`,
        {
          query: {
            active_project: message.activeProject,
            refresh: message.refresh,
          },
        },
      );
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
        // Carried across so a surface can tell a hub that lacks an endpoint
        // from one that answered with a real error
        status: e instanceof ApiError ? e.status : undefined,
      } as Envelope<unknown>);
    });
  // Keep the message channel open for the async response above
  return true;
});

// Tell a tab when its URL changes, including single-page-app navigation that
// fires no document load. Content scripts used to poll window.location on an
// interval for this; letting the browser report it means no timer runs in
// any page the extension touches.
// Only the two single-page apps need this; everywhere else a URL change
// comes with a document load that starts the content script afresh.
const SPA_HOSTS = ["github.com", "www.overleaf.com", "overleaf.com"];

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) {
    return;
  }
  let host: string;
  try {
    host = new URL(changeInfo.url).hostname;
  } catch {
    return;
  }
  if (!SPA_HOSTS.includes(host)) {
    return;
  }
  chrome.tabs
    .sendMessage(tabId, { type: "url.changed", url: changeInfo.url })
    // The tab may not have a content script of ours listening yet
    .catch(() => undefined);
});
