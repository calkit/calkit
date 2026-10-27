import { getOverleafProjectId } from "../core/detect";
import {
  renderFailure,
  renderHubPicker,
  renderProjectPicker,
} from "../core/pickers";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { isUnsupportedByHub, RequestFailed, send } from "../core/messages";
import type {
  GithubRepo,
  OverleafLinkPublic,
  OverleafSyncStatus,
  OverleafSyncStatusFile,
  ProjectPublic,
} from "../core/types";
import {
  clear,
  el,
  launcherPosition,
  errorMessage,
  loading,
  mountPanel,
  type Panel,
  textInput,
} from "../core/ui";

const PANEL_ID = "calkit-overleaf-panel";
const LAUNCHER_ID = "calkit-overleaf-launcher";
const TOKEN_PANEL_ID = "calkit-overleaf-token-panel";
const OVERLEAF_GIT_SETTINGS =
  "https://www.overleaf.com/user/settings#git-integration";
const OVERLEAF_TOKEN_RE = /\bolp_[A-Za-z0-9]{20,}\b/;

let panel: Panel | null = null;
let currentProjectId: string | null = null;
let hubWebUrl = "https://calkit.io";
// The last status found for this page, so opening the panel shows it at
// once instead of waiting for the hub to check Overleaf all over again
let lastCheck: {
  overleafProjectId: string;
  hubWebUrl: string;
  link: OverleafLinkPublic;
  status: OverleafSyncStatus;
  // What the last sync did, kept through the check that follows it
  notice?: string;
} | null = null;
// Bumped by each load, each sync, and each sign-in change, so a check
// that finishes after any of them doesn't draw over it
let loadGeneration = 0;
let tokenWatcher: MutationObserver | null = null;

/**
 * Whether a failure is about the user's Overleaf Git token, missing or
 * rejected, which the hub needs to read the project, rather than their
 * Calkit credentials.
 */
function isOverleafTokenProblem(e: unknown): boolean {
  return (
    e instanceof RequestFailed &&
    e.status === 401 &&
    /overleaf/i.test(e.message)
  );
}

/**
 * Ask for an Overleaf Git token, and save it to the hub, or, without
 * Overleaf Premium, connect the browser's Overleaf login instead.
 */
function renderTokenForm(
  container: HTMLElement,
  problem: string,
  reload: () => void,
): void {
  const rejected = problem.includes("rejected");
  const sessionRejected = rejected && problem.includes("session");
  const connectMessage = el("div", { class: "small" });
  const connect = el("button", {
    class: sessionRejected ? "action" : "action secondary",
    text: "Connect with Overleaf login",
  });
  connect.addEventListener("click", async () => {
    connect.disabled = true;
    clear(connectMessage).append(loading("Connecting"));
    try {
      await send({ type: "overleaf.connectSession" });
      reload();
    } catch (e) {
      connect.disabled = false;
      clear(connectMessage).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const connectSection = el("div", { style: { marginTop: "12px" } }, [
    el("div", {
      class: "small",
      text: sessionRejected
        ? "Overleaf no longer accepts the Overleaf login Calkit saved. " +
          "Connect it again to keep syncing."
        : "No Overleaf Premium? Calkit can sync using your Overleaf " +
          "login instead of a token.",
    }),
    el("div", { class: "actions" }, [connect]),
    connectMessage,
  ]);
  if (sessionRejected) {
    container.append(connectSection);
    return;
  }
  const input = textInput({ placeholder: "olp_..." });
  input.type = "password";
  const message = el("div", { class: "small" });
  const save = el("button", { class: "action", text: "Save token" });
  save.addEventListener("click", async () => {
    const token = input.value.trim();
    if (!token.startsWith("olp_")) {
      clear(message).append(errorMessage("Overleaf tokens start with olp_"));
      return;
    }
    save.disabled = true;
    clear(message).append(loading("Saving"));
    try {
      await send({ type: "overleaf.setToken", token });
      reload();
    } catch (e) {
      save.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("div", {
      class: "small",
      text: rejected
        ? "Overleaf rejected your Git token. It may have expired or " +
          "been revoked."
        : "Calkit needs an Overleaf Git token to read this project.",
    }),
    el("div", { class: "dim small", style: { marginTop: "6px" } }, [
      document.createTextNode("Generate one under Git Integration in "),
      el("a", {
        text: "your Overleaf account settings",
        href: OVERLEAF_GIT_SETTINGS,
        attrs: { target: "_blank" },
      }),
      document.createTextNode(
        ". Calkit offers to save it from there, or paste it here.",
      ),
    ]),
    input,
    el("div", { class: "actions" }, [
      save,
      el("button", {
        class: "action secondary",
        text: "Check again",
        onClick: reload,
      }),
    ]),
    message,
    connectSection,
  );
}

/**
 * Show a failure, offering to connect Overleaf when that's what's missing,
 * so a first link or import works without Premium too.
 */
function renderOverleafFailure(e: unknown, reload: () => void): HTMLElement {
  if (isOverleafTokenProblem(e)) {
    const container = el("div");
    renderTokenForm(
      container,
      e instanceof Error ? e.message : String(e),
      reload,
    );
    return container;
  }
  return renderFailure(e, { onSignedIn: reload });
}

/**
 * Offer to save an Overleaf Git token to Calkit as soon as Overleaf shows
 * one, which it only does once, right after it's generated.
 *
 * Only ever on the user's click: the token is read from the page they're
 * looking at, and nothing is sent until they say so.
 */
function watchForNewToken(): void {
  if (tokenWatcher) {
    return;
  }
  const texts = (): string[] => [
    ...Array.from(document.querySelectorAll("input"), (input) => input.value),
    document.body.innerText,
  ];
  // Only whether one is showing until the user asks to save it, so the
  // token itself is never held before then
  let showing = false;
  tokenWatcher = new MutationObserver(() => {
    const visible = texts().some((text) => OVERLEAF_TOKEN_RE.test(text));
    if (visible === showing) {
      return;
    }
    showing = visible;
    if (!visible) {
      document.getElementById(TOKEN_PANEL_ID)?.remove();
      return;
    }
    const tokenPanel = mountPanel({ id: TOKEN_PANEL_ID, title: "Calkit" });
    const message = el("div", { class: "small" });
    const save = el("button", { class: "action", text: "Save to Calkit" });
    save.addEventListener("click", async () => {
      const token = texts()
        .map((text) => text.match(OVERLEAF_TOKEN_RE)?.[0])
        .find(Boolean);
      if (!token) {
        clear(message).append(
          errorMessage("The token is no longer on the page"),
        );
        return;
      }
      save.disabled = true;
      clear(message).append(loading("Saving"));
      try {
        await send({ type: "overleaf.setToken", token });
        clear(tokenPanel.body).append(
          el("div", {
            class: "small",
            text:
              "Saved. Go back to your Overleaf project and press Check " +
              "again in the Calkit panel.",
          }),
        );
      } catch (e) {
        save.disabled = false;
        clear(message).append(
          errorMessage(e instanceof Error ? e.message : String(e)),
        );
      }
    });
    tokenPanel.body.append(
      el("div", {
        class: "small",
        text:
          "Save this Overleaf Git token to Calkit, so it can check and " +
          "sync your Overleaf projects?",
      }),
      el("div", { class: "actions" }, [save]),
      message,
    );
  });
  tokenWatcher.observe(document.body, { childList: true, subtree: true });
}

function fileRow(file: OverleafSyncStatusFile): HTMLElement {
  const stale = file.stage_status && file.stage_status.status !== "up-to-date";
  const stateLabel = {
    new: "not on Overleaf",
    modified: "changed",
    deleted: "removed",
  }[file.state];
  return el("div", { class: "row" }, [
    el("div", { class: "grow" }, [
      el("div", { class: "name", text: file.path }),
      el("div", { class: "dim small", text: stateLabel }),
    ]),
    file.figure && el("span", { class: "badge info", text: "figure" }),
    stale &&
      el("span", {
        class: "badge warn",
        text: "stale",
        title:
          `Produced by stage '${file.stage}', which is ` +
          `${file.stage_status?.status}; run the pipeline before syncing`,
      }),
  ]);
}

function renderStatus(
  body: HTMLElement,
  link: OverleafLinkPublic,
  status: OverleafSyncStatus,
  reload: () => void,
): void {
  clear(body);
  const figures = status.files_to_push.filter((f) => f.figure);
  const others = status.files_to_push.filter((f) => !f.figure);
  const canWrite = ["write", "admin", "owner"].includes(
    link.current_user_access ?? "",
  );
  body.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${link.project_owner_name}/${link.project_name}`,
          href: projectUrl(
            hubWebUrl,
            link.project_owner_name,
            link.project_name,
          ),
        }),
        el("div", {
          class: "dim small",
          text: `Synced folder: ${status.path}`,
        }),
      ]),
      status.in_sync
        ? el("span", { class: "badge ok", text: "in sync" })
        : el("span", {
            class: figures.length ? "badge danger" : "badge warn",
            text: figures.length
              ? `${figures.length} figure${
                  figures.length === 1 ? "" : "s"
                } to sync`
              : "out of sync",
          }),
    ]),
  );
  if (status.in_sync) {
    body.append(
      el("div", {
        class: "dim small",
        style: { paddingTop: "6px" },
        text: "Everything here matches the Calkit project.",
      }),
    );
  }
  if (figures.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Figures to sync",
      }),
      ...figures.map(fileRow),
    );
  }
  if (others.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Other files to sync",
      }),
      ...others.map(fileRow),
    );
  }
  if (status.files_to_delete.length) {
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Removed from the project",
      }),
      ...status.files_to_delete.map(fileRow),
    );
  }
  if (status.commits_from_overleaf > 0) {
    const count = status.commits_from_overleaf;
    body.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text:
          `${count} Overleaf ${count === 1 ? "change" : "changes"} ` +
          "will come back into the project on the next sync.",
      }),
    );
  }
  const syncButton = el("button", {
    class: "action",
    text: "Sync now",
    disabled: !canWrite || status.in_sync,
    title: canWrite
      ? "Push project files to Overleaf and pull Overleaf edits back"
      : "You need write access to this project to sync",
  });
  const message = el("div", { class: "small" });
  syncButton.addEventListener("click", async () => {
    loadGeneration++;
    syncButton.disabled = true;
    clear(message).append(loading("Syncing"));
    try {
      const result = await send({
        type: "overleaf.sync",
        owner: link.project_owner_name,
        project: link.project_name,
        path: status.path,
      });
      // Shown as in sync straight away, since that's what a sync leaves,
      // while the hub confirms it
      lastSyncNeeded = false;
      lastCheck = {
        overleafProjectId: link.overleaf_project_id,
        hubWebUrl,
        link,
        status: {
          ...status,
          in_sync: true,
          files_to_push: [],
          files_to_delete: [],
          commits_from_overleaf: 0,
        },
        notice:
          `Synced. ${result.commits_from_overleaf} change` +
          `${result.commits_from_overleaf === 1 ? "" : "s"} came from ` +
          "Overleaf.",
      };
      reload();
    } catch (e) {
      syncButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  body.append(
    el("div", { class: "actions" }, [
      syncButton,
      el("button", {
        class: "action secondary",
        text: "Refresh",
        onClick: reload,
      }),
    ]),
    message,
  );
}

/**
 * Let the user make a new Calkit project for this Overleaf project, or
 * pick one they already have.
 *
 * Starting down either path hides the other, so a half-filled form never
 * sits next to a list of unrelated projects.
 */
async function renderPicker(
  body: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  clear(body);
  const back = (text: string) =>
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text,
        onClick: () => void renderPicker(body, overleafProjectId, reload),
      }),
    ]);
  const attachContainer = el("div");
  const start = el("div", {}, [
    el("div", {
      class: "dim small",
      text: "This paper isn't part of a Calkit project yet.",
    }),
    el("div", { class: "actions" }, [
      el("button", {
        class: "action",
        text: "Make this paper reproducible",
        onClick: () => {
          start.remove();
          existing.remove();
          const form = el("div");
          clear(attachContainer).append(
            form,
            back("Use a project I already have"),
          );
          void renderAttachForm(form, overleafProjectId, reload);
        },
      }),
    ]),
  ]);
  const search = textInput({
    placeholder: "Search your projects",
  });
  const results = el("div", { class: "stack", style: { marginTop: "6px" } });
  const existing = el("div", {}, [
    el("div", {
      class: "dim small",
      style: { marginTop: "12px" },
      text: "Or add it to a project you already have:",
    }),
    search,
    results,
  ]);
  const chosen = el("div", { class: "stack" });
  const chooseProject = async (project: ProjectPublic) => {
    start.remove();
    existing.remove();
    const message = el("div", { class: "small" }, [loading("Checking")]);
    clear(chosen).append(
      el(
        "div",
        {
          class: "muted-box",
          style: { borderLeft: "3px solid var(--ck-main)" },
        },
        [
          el("div", { class: "dim small", text: "Adding this paper to" }),
          el("div", {
            text: `${project.owner_account_name}/${project.name}`,
          }),
          el("div", { class: "dim small", text: project.title }),
        ],
      ),
      message,
      back("Pick a different project"),
    );
    try {
      const statuses = await send({
        type: "overleaf.status",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectId,
      });
      if (statuses.length) {
        // Reading the status indexes the link server side, so a plain
        // reload now finds it
        reload();
        return;
      }
      clear(message).append(
        el("div", { class: "stack" }, [
          el("div", {
            class: "dim small",
            text:
              "Calkit will copy this paper's files into the project and " +
              "keep them in sync with Overleaf.",
          }),
          ...renderImportForm(project, overleafProjectId, reload),
        ]),
      );
    } catch (e) {
      clear(message).append(
        renderOverleafFailure(e, () => void chooseProject(project)),
      );
    }
  };
  const runSearch = async () => {
    clear(results).append(loading());
    try {
      const projects = await send({
        type: "projects.list",
        searchFor: search.value.trim() || undefined,
        limit: 10,
      });
      clear(results);
      if (!projects.data.length) {
        results.append(el("div", { class: "dim small", text: "No projects" }));
        return;
      }
      for (const project of projects.data) {
        results.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", {
                text: `${project.owner_account_name}/${project.name}`,
              }),
              el("div", { class: "dim small", text: project.title }),
            ]),
            el("button", {
              class: "action secondary",
              text: "Choose",
              onClick: () => void chooseProject(project),
            }),
          ]),
        );
      }
    } catch (e) {
      clear(results).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void runSearch(), 300);
  });
  body.append(start, attachContainer, existing, chosen);
  await runSearch();
}

/** The name Overleaf shows for this project. */
function overleafProjectTitle(): string {
  const meta = document.querySelector<HTMLMetaElement>(
    'meta[name="ol-projectName"]',
  );
  if (meta?.content.trim()) {
    return meta.content.trim();
  }
  // The tab reads, e.g., "My paper - Online LaTeX Editor Overleaf"
  return document.title.replace(/\s+-\s+[^-]*Overleaf[^-]*$/i, "").trim();
}

/** A project name from a title, the way the hub makes one. */
function projectSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\w-]+/g, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

/**
 * Make a Calkit project for this Overleaf project, so the paper becomes a
 * pipeline stage whose figures and values can be traced and kept current.
 *
 * The project is a GitHub repo with the paper in a folder inside it,
 * either a new repo or one that already holds the analysis behind the
 * paper. Either way the hub needs a GitHub account to own it and the
 * Calkit app installed to write to it, so those come first, rather than
 * as an error after the form is filled in.
 */
async function renderAttachForm(
  container: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  // Where the hub connects GitHub and installs its app, whose name differs
  // between hubs, and which sends a user with no installation to GitHub
  const accountsUrl = `${hubWebUrl}/settings?tab=connected-accounts`;
  const openAccounts = () => window.open(accountsUrl, "_blank", "noopener");
  const retry = () =>
    void renderAttachForm(container, overleafProjectId, reload);
  const blocked = (text: string, action: string) =>
    clear(container).append(
      el("div", { class: "small", text }),
      el("div", { class: "actions" }, [
        el("button", { class: "action", text: action, onClick: openAccounts }),
        el("button", {
          class: "action secondary",
          text: "Check again",
          onClick: retry,
        }),
      ]),
    );
  clear(container).append(loading("Checking your GitHub connection"));
  let githubName: string;
  try {
    const auth = await send({ type: "auth.state" });
    if (!auth.user?.github_username) {
      blocked(
        "Calkit keeps a project's files in a GitHub repo, so connect a " +
          "GitHub account first.",
        "Connect GitHub",
      );
      return;
    }
    githubName = auth.user.github_username;
    const installations = await send({ type: "github.installations" });
    if (!installations.total_count) {
      blocked(
        "Install the Calkit app on GitHub, so Calkit can create and update " +
          "the project's repo.",
        "Install the Calkit app",
      );
      return;
    }
  } catch (e) {
    // The hub's GitHub token can be expired or revoked even with a GitHub
    // username on the account, which reconnecting fixes
    if (
      e instanceof RequestFailed &&
      e.status === 401 &&
      /github/i.test(e.message)
    ) {
      blocked(
        "Calkit's connection to GitHub has expired. Reconnect it to " +
          "continue.",
        "Reconnect GitHub",
      );
      return;
    }
    clear(container).append(renderOverleafFailure(e, retry));
    return;
  }
  clear(container);
  const existsOnGithub = el("input", { type: "checkbox" });
  existsOnGithub.style.width = "auto";
  // Only for a new repo, since the hub matches an existing one's visibility
  const isPublic = el("input", { type: "checkbox" });
  isPublic.style.width = "auto";
  isPublic.addEventListener("change", () => describe());
  const publicField = el(
    "label",
    { class: "row", style: { fontWeight: "400" } },
    [isPublic, el("div", { class: "grow small", text: "Make it public" })],
  );
  const repoInput = textInput({
    placeholder: "Start typing your GitHub repo name",
  });
  const repoResults = el("div", { class: "stack" });
  const repoFields = el("div", { class: "stack" }, [
    el("label", { text: "GitHub repo" }),
    repoInput,
    repoResults,
    el("div", { class: "dim small" }, [
      document.createTextNode("Only repos the Calkit app can access show. "),
      el("a", { text: "Give it access to more", href: accountsUrl }),
    ]),
  ]);
  const titleInput = textInput({
    value: overleafProjectTitle(),
    placeholder: "My project",
  });
  const nameInput = textInput({
    value: projectSlug(titleInput.value),
    placeholder: "my-project",
  });
  // The name follows the title until it's edited itself
  let nameEdited = false;
  nameInput.addEventListener("input", () => {
    nameEdited = true;
    describe();
  });
  titleInput.addEventListener("input", () => {
    if (!nameEdited) {
      nameInput.value = projectSlug(titleInput.value);
    }
    describe();
  });
  const doc = documentFields(() => describe());
  // Where the document's files will go, since committing into an existing
  // repo is the part worth knowing before clicking
  const where = el("div", { class: "dim small" });
  const message = el("div", { class: "small" });
  let repos: GithubRepo[] | null = null;
  let chosenRepo: GithubRepo | null = null;
  const describe = () => {
    const folder = doc.folder();
    where.textContent = existsOnGithub.checked
      ? chosenRepo
        ? `Calkit will commit this document's files to ${folder}/ in ` +
          `${chosenRepo.full_name}, and keep them in sync with Overleaf.`
        : ""
      : `Calkit will create a ${isPublic.checked ? "public" : "private"} ` +
        `repo, ${githubName}/` +
        `${nameInput.value.trim() || "..."}, with this document's files in ` +
        `${folder}/, and keep them in sync with Overleaf.`;
  };
  const renderRepoResults = () => {
    const query = repoInput.value.trim().toLowerCase();
    clear(repoResults);
    if (!repos) {
      return;
    }
    const matching = repos
      .filter((repo) => repo.full_name.toLowerCase().includes(query))
      .slice(0, 8);
    for (const repo of matching) {
      repoResults.append(
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "small", text: repo.full_name }),
            repo.description
              ? el("div", { class: "dim small", text: repo.description })
              : null,
          ]),
          el("button", {
            class: "action secondary",
            text: chosenRepo?.full_name === repo.full_name ? "Chosen" : "Use",
            disabled: chosenRepo?.full_name === repo.full_name,
            onClick: () => {
              chosenRepo = repo;
              repoInput.value = repo.full_name;
              // The project takes the repo's name unless renamed, since
              // that's the pairing everything else assumes
              if (!nameEdited) {
                nameInput.value = repo.name;
              }
              renderRepoResults();
              describe();
            },
          }),
        ]),
      );
    }
    if (!matching.length) {
      repoResults.append(
        el("div", { class: "dim small", text: "No matching repos" }),
      );
    }
  };
  const loadRepos = async () => {
    clear(repoResults).append(loading("Reading your GitHub repos"));
    try {
      repos = await send({ type: "github.repos" });
      renderRepoResults();
    } catch (e) {
      clear(repoResults).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  repoInput.addEventListener("input", renderRepoResults);
  const syncGithubFields = () => {
    repoFields.style.display = existsOnGithub.checked ? "" : "none";
    publicField.style.display = existsOnGithub.checked ? "none" : "";
    // A repo picked before switching to a new one would otherwise still be
    // where the paper goes
    if (!existsOnGithub.checked && chosenRepo) {
      chosenRepo = null;
      repoInput.value = "";
      if (!nameEdited) {
        nameInput.value = projectSlug(titleInput.value);
      }
      renderRepoResults();
    }
    if (existsOnGithub.checked && repos === null) {
      void loadRepos();
    }
    describe();
  };
  existsOnGithub.addEventListener("change", syncGithubFields);
  syncGithubFields();
  // Kept once made, so retrying after the import fails doesn't try to
  // create the same project again
  let created: ProjectPublic | null = null;
  const attach = el("button", { class: "action", text: "Create project" });
  attach.addEventListener("click", async () => {
    attach.disabled = true;
    try {
      const name = nameInput.value.trim();
      if (!name) {
        throw new Error("A project name is required");
      }
      if (existsOnGithub.checked && !chosenRepo) {
        throw new Error("Pick the GitHub repo to use");
      }
      if (!created) {
        clear(message).append(loading("Creating the project"));
        try {
          created = await send({
            type: "projects.create",
            name,
            title: titleInput.value.trim() || name,
            gitRepoUrl: chosenRepo
              ? `https://github.com/${chosenRepo.full_name}`
              : undefined,
            isPublic: !chosenRepo && isPublic.checked,
          });
        } catch (e) {
          // An earlier try that stopped partway, e.g., when the panel was
          // reloaded, already made the project, so carry on with that one
          if (!(e instanceof RequestFailed && e.status === 409)) {
            throw e;
          }
          const existing = await send({
            type: "projects.list",
            githubRepo: chosenRepo?.full_name ?? `${githubName}/${name}`,
            limit: 1,
          });
          if (!existing.data.length) {
            throw e;
          }
          created = existing.data[0];
        }
        // Nothing above can change what was made
        for (const input of [existsOnGithub, isPublic, repoInput, nameInput]) {
          input.disabled = true;
        }
        titleInput.disabled = true;
        // The project this paper now belongs to is the one to work in
        await send({
          type: "settings.set",
          update: {
            activeProject: `${created.owner_account_name}/${created.name}`,
          },
        });
      }
      clear(message).append(loading("Bringing in the document from Overleaf"));
      await send({
        type: "overleaf.import",
        owner: created.owner_account_name,
        project: created.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: doc.folder(),
        kind: doc.kind.value,
      });
      reload();
    } catch (e) {
      attach.disabled = false;
      // Retried in place, so connecting Overleaf here doesn't start over
      clear(message).append(renderOverleafFailure(e, () => attach.click()));
      // What the hub says when the app can't reach the account or repo
      if (String(e instanceof Error ? e.message : e).includes("App not")) {
        message.append(
          el("div", { class: "actions" }, [
            el("button", {
              class: "action secondary",
              text: "Give the Calkit app access",
              onClick: openAccounts,
            }),
          ]),
        );
      }
    }
  });
  container.append(
    el("label", { text: "Project title" }),
    titleInput,
    el("label", { text: "Project name" }),
    nameInput,
    el("label", { class: "row", style: { fontWeight: "400" } }, [
      existsOnGithub,
      el("div", {
        class: "grow small",
        text: "This project already has a GitHub repo",
      }),
    ]),
    repoFields,
    publicField,
    ...doc.fields,
    where,
    el("div", { class: "actions" }, [attach]),
    message,
  );
}

/**
 * Type and folder fields for an Overleaf document going into a project,
 * the folder following the type until it's edited.
 */
function documentFields(onChange: () => void = () => {}): {
  kind: HTMLSelectElement;
  folder: () => string;
  fields: HTMLElement[];
} {
  const types: [string, string, string][] = [
    ["journal-article", "Journal article", "paper"],
    ["conference-paper", "Conference paper", "paper"],
    ["report", "Report", "report"],
    ["book", "Book", "book"],
    ["masters-thesis", "Master's thesis", "thesis"],
    ["phd-thesis", "PhD thesis", "thesis"],
    ["other", "Other", "document"],
  ];
  const kind = el("select");
  for (const [value, label] of types) {
    kind.append(el("option", { value, text: label }));
  }
  const defaultFolder = () =>
    types.find(([value]) => value === kind.value)?.[2] ?? "document";
  const path = textInput({ value: defaultFolder() });
  let pathEdited = false;
  path.addEventListener("input", () => {
    pathEdited = true;
    onChange();
  });
  kind.addEventListener("change", () => {
    if (!pathEdited) {
      path.value = defaultFolder();
    }
    onChange();
  });
  return {
    kind,
    folder: () => path.value.trim() || defaultFolder(),
    fields: [
      el("label", { text: "Type" }),
      kind,
      el("label", { text: "Folder for this document" }),
      path,
    ],
  };
}

function renderImportForm(
  project: ProjectPublic,
  overleafProjectId: string,
  reload: () => void,
): HTMLElement[] {
  const doc = documentFields();
  const importButton = el("button", {
    class: "action",
    text: `Add to ${project.name}`,
  });
  const message = el("div", { class: "small" });
  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    clear(message).append(loading("Bringing in the document from Overleaf"));
    try {
      await send({
        type: "overleaf.import",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: doc.folder(),
        kind: doc.kind.value,
      });
      await send({
        type: "settings.set",
        update: {
          activeProject: `${project.owner_account_name}/${project.name}`,
        },
      });
      reload();
    } catch (e) {
      importButton.disabled = false;
      clear(message).append(
        renderOverleafFailure(e, () => importButton.click()),
      );
    }
  });
  return [
    ...doc.fields,
    el("div", { class: "actions" }, [importButton]),
    message,
  ];
}

async function load(overleafProjectId: string): Promise<void> {
  if (!panel) {
    return;
  }
  const body = panel.body;
  const generation = ++loadGeneration;
  const current = () => generation === loadGeneration;
  clear(body).append(loading());
  const reload = () => void load(overleafProjectId);
  try {
    hubWebUrl = await getHubWebUrl();
    const settings = await send({ type: "settings.get" });
    const pickers = el(
      "div",
      { class: "muted-box stack", style: { marginBottom: "8px" } },
      [
        await renderHubPicker(reload),
        await renderProjectPicker({
          activeProject: settings.activeProject,
          onChange: reload,
        }),
      ],
    );
    const cached =
      lastCheck?.overleafProjectId === overleafProjectId &&
      lastCheck.hubWebUrl === hubWebUrl
        ? lastCheck
        : null;
    const content = el("div");
    clear(body).append(pickers, content);
    const showNotice = () => {
      if (cached?.notice) {
        content.append(
          el("div", {
            class: "dim small",
            style: { marginTop: "6px" },
            text: cached.notice,
          }),
        );
      }
    };
    if (cached) {
      renderStatus(content, cached.link, cached.status, reload);
      showNotice();
      content.append(loading("Checking for changes"));
    } else {
      content.append(loading("Looking for the linked project"));
    }
    // The index answers at once when this Overleaf project has been seen
    // before; otherwise the hub reads through the user's projects, active
    // one first, and remembers what it finds
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    if (!current()) {
      return;
    }
    const links = lookup.links;
    lastUnlinked = !links.length && lookup.projects_remaining === 0;
    if (!links.length) {
      clear(body).append(pickers);
      if (lookup.projects_remaining > 0) {
        body.append(
          el("div", { class: "dim small" }, [
            document.createTextNode(
              `Checked ${lookup.projects_scanned} project(s); ` +
                `${lookup.projects_remaining} left to look through.`,
            ),
          ]),
          el("div", { class: "actions" }, [
            el("button", {
              class: "action secondary",
              text: "Keep looking",
              onClick: reload,
            }),
          ]),
        );
      }
      const chooser = el("div");
      body.append(chooser);
      await renderPicker(chooser, overleafProjectId, reload);
      return;
    }
    // A folder in more than one project is rare, so the first link is the
    // one shown, with the rest offered as alternatives underneath
    const link = links[0];
    if (!cached) {
      clear(content).append(
        loading(`Checking ${link.project_owner_name}/${link.project_name}`),
      );
    }
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    });
    if (!current()) {
      return;
    }
    if (!statuses.length) {
      clear(content).append(
        el("div", {
          class: "dim small",
          text:
            "The project no longer syncs a folder with this Overleaf " +
            "project. Reload to pick a different project.",
        }),
      );
      return;
    }
    lastTokenProblem = false;
    lastSyncNeeded = !statuses[0].in_sync;
    lastCheck = { overleafProjectId, hubWebUrl, link, status: statuses[0] };
    renderStatus(content, link, statuses[0], reload);
    showNotice();
    if (links.length > 1) {
      content.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "8px" },
          text: `Also linked from ${links.length - 1} other project(s).`,
        }),
      );
    }
  } catch (e) {
    if (!current()) {
      return;
    }
    clear(body);
    if (e instanceof RequestFailed && e.notSignedIn) {
      // With a hub picker alongside, since credentials are per hub and a
      // signed-out panel otherwise has no way back to the right one
      body.append(renderFailure(e, { onSignedIn: reload }));
      return;
    }
    if (isUnsupportedByHub(e)) {
      // Hubs deploy separately from the extension, so this is a version
      // gap rather than anything the user did wrong. Saying "Not Found",
      // which is all the hub sends back for a route it doesn't have,
      // would send them looking for a missing project instead
      body.append(
        errorMessage(
          `${hubWebUrl.replace(/^https?:\/\//, "")} doesn't support ` +
            "Overleaf sync yet.",
        ),
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text: "Switch to a hub running a newer version to sync from here.",
        }),
        el("div", { style: { marginTop: "8px" } }, [
          await renderHubPicker(reload),
        ]),
      );
      return;
    }
    // The picker stays, since the problem may be with this hub, e.g., an
    // Overleaf token only another hub has, and switching is the way out
    const hubPicker = el("div", { style: { marginBottom: "8px" } }, [
      await renderHubPicker(reload),
    ]);
    if (isOverleafTokenProblem(e)) {
      body.append(hubPicker);
      renderTokenForm(body, e instanceof Error ? e.message : String(e), reload);
      return;
    }
    body.append(
      hubPicker,
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

/**
 * The button that opens the panel, and what it collapses back to.
 *
 * Its tone carries the one thing worth interrupting for: amber means a
 * sync would do something, which is how a stale figure gets noticed
 * without the panel opening on top of the document uninvited. A paper
 * not in any project gets it too, since linking it is the first step.
 */
type LauncherTone = "idle" | "attention" | "reconnect" | "unlinked";

function mountLauncher(onClick: () => void, tone: LauncherTone = "idle"): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  const host = el("div", { attrs: { id: LAUNCHER_ID } });
  Object.assign(host.style, {
    position: "fixed",
    ...launcherPosition(),
    zIndex: "2147482999",
  });
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = `
    button {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica,
        Arial, sans-serif;
      font-size: 12px;
      font-weight: 600;
      color: #ffffff;
      background: #009688;
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    button:hover { filter: brightness(1.1); }
    button.attention { background: #d69e2e; }
  `;
  const button = el("button", {
    text: {
      idle: "Calkit",
      attention: "Calkit: sync needed",
      reconnect: "Calkit: reconnect Overleaf",
      unlinked: "Calkit: not linked",
    }[tone],
    class: tone === "idle" ? "" : "attention",
  });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

// Remembered so a closed panel can still show that something is waiting
let lastSyncNeeded = false;
let lastTokenProblem = false;
let lastUnlinked = false;

function openPanel(overleafProjectId: string): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  panel = mountPanel({
    id: PANEL_ID,
    title: "Calkit",
    onClose: () => {
      panel = null;
      mountLauncher(
        () => openPanel(overleafProjectId),
        lastTokenProblem
          ? "reconnect"
          : lastUnlinked
          ? "unlinked"
          : lastSyncNeeded
          ? "attention"
          : "idle",
      );
    },
  });
  void load(overleafProjectId);
}

function teardown(): void {
  tokenWatcher?.disconnect();
  tokenWatcher = null;
  document.getElementById(TOKEN_PANEL_ID)?.remove();
  document.getElementById(LAUNCHER_ID)?.remove();
  panel?.remove();
  panel = null;
  currentProjectId = null;
}

function sync(): void {
  if (new URL(window.location.href).pathname.startsWith("/user/settings")) {
    watchForNewToken();
    return;
  }
  const overleafProjectId = getOverleafProjectId(window.location.href);
  if (!overleafProjectId) {
    teardown();
    return;
  }
  if (overleafProjectId === currentProjectId) {
    return;
  }
  currentProjectId = overleafProjectId;
  // A button, not an open panel: this sits on top of someone's document,
  // and opening uninvited is the extension deciding it matters more than
  // what they were doing. The check below is what earns the click.
  mountLauncher(() => openPanel(overleafProjectId));
  void checkSyncStatus(overleafProjectId);
}

/**
 * Ask whether this Overleaf project has anything waiting, and say so on
 * the button.
 *
 * The whole point of the panel is catching a figure that was regenerated
 * and never made it to Overleaf, which nobody would think to open a panel
 * to find out. So the question is asked quietly and only the answer
 * shows: an amber button when a sync would do something.
 */
async function checkSyncStatus(overleafProjectId: string): Promise<void> {
  // An answer from a hub or sign-in that has since changed describes
  // something else, so it's dropped rather than cached
  const generation = loadGeneration;
  const hub = await getHubWebUrl();
  const current = async () =>
    generation === loadGeneration && (await getHubWebUrl()) === hub;
  try {
    const settings = await send({ type: "settings.get" });
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    const link = lookup.links[0];
    if (!link) {
      if (!(await current())) {
        return;
      }
      // Only when every project was checked, since the rest might link it
      lastUnlinked = lookup.projects_remaining === 0;
      if (lastUnlinked && !panel && currentProjectId === overleafProjectId) {
        mountLauncher(() => openPanel(overleafProjectId), "unlinked");
      }
      return;
    }
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    });
    if (!(await current())) {
      return;
    }
    lastTokenProblem = false;
    lastUnlinked = false;
    lastSyncNeeded = Boolean(statuses.length) && !statuses[0].in_sync;
    lastCheck = statuses.length
      ? { overleafProjectId, hubWebUrl: hub, link, status: statuses[0] }
      : null;
    // Nothing to say if the panel was opened in the meantime, or if the
    // page moved on to another project
    if (panel || currentProjectId !== overleafProjectId) {
      return;
    }
    mountLauncher(
      () => openPanel(overleafProjectId),
      lastSyncNeeded ? "attention" : "idle",
    );
  } catch (e) {
    if (!(await current())) {
      return;
    }
    // A token problem is worth a nudge, since nothing works until it's
    // fixed; anything else the panel explains when opened
    lastTokenProblem = isOverleafTokenProblem(e);
    if (lastTokenProblem && !panel && currentProjectId === overleafProjectId) {
      mountLauncher(() => openPanel(overleafProjectId), "reconnect");
    }
  }
}

/**
 * Re-check after a save, since that is exactly when the answer changes.
 *
 * Overleaf saves continuously, so this listens for the explicit save
 * people still press rather than trying to observe every keystroke, and
 * waits a moment for Overleaf to have written it before asking.
 */
function watchForSaves(): void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  document.addEventListener(
    "keydown",
    (event) => {
      const isSave =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (!isSave || !currentProjectId) {
        return;
      }
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (!currentProjectId) {
          return;
        }
        // A save is when a figure most often stops matching what's on
        // Overleaf, so the button has to notice it too, not just an
        // already-open panel
        if (panel) {
          void load(currentProjectId);
        } else {
          void checkSyncStatus(currentProjectId);
        }
      }, 2000);
    },
    true,
  );
}

watchForSaves();
runContentScript({
  id: "overleaf",
  sync,
  teardown,
  authChanged: () => {
    if (!currentProjectId) {
      return;
    }
    const overleafProjectId = currentProjectId;
    // What the last session found says nothing about this one
    loadGeneration++;
    lastSyncNeeded = false;
    lastTokenProblem = false;
    lastUnlinked = false;
    lastCheck = null;
    if (panel) {
      void load(overleafProjectId);
    } else {
      mountLauncher(() => openPanel(overleafProjectId));
      void checkSyncStatus(overleafProjectId);
    }
  },
});
