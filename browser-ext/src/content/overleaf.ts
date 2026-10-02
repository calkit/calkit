import { getOverleafProjectId } from "../core/detect";
import {
  renderFailure,
  renderHubPicker,
  renderProjectPicker,
} from "../core/pickers";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { isUnsupportedByHub, RequestFailed, send } from "../core/messages";
import {
  componentBadge,
  componentLabel,
  componentProblem,
  componentsSummary,
  editUrl,
  sortComponents,
  valueText,
} from "../core/components";
import type {
  PublicationComponent,
  PublicationComponents,
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

let panel: Panel | null = null;
let currentProjectId: string | null = null;
let hubWebUrl = "https://calkit.io";

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

/**
 * One component the paper shows, with what is wrong with it and a way into
 * the project to fix it.
 *
 * Overleaf can't run the pipeline, so the useful action is not "rebuild"
 * but "go and change what makes this", which is a link into the hub at the
 * producing script.
 */
function componentRow(
  item: PublicationComponent,
  link: OverleafLinkPublic,
): HTMLElement {
  const badge = componentBadge(item);
  const problem = componentProblem(item);
  const shown = valueText(item.current_value);
  const pages = item.pages ?? [];
  const where = pages.length
    ? ` \u00b7 ${pages.length === 1 ? "p." : "pp."} ${pages.join(", ")}`
    : "";
  return el("div", { class: "row" }, [
    el("div", { class: "grow" }, [
      el("div", { class: "name", text: componentLabel(item) }),
      el("div", {
        class: "dim small",
        text:
          (item.kind === "value" && shown ? `${shown} \u00b7 ` : "") +
          (item.stage ? `stage ${item.stage}` : item.kind) +
          where,
      }),
      problem && el("div", { class: "dim small", text: problem }),
    ]),
    badge && el("span", { class: `badge ${badge.level}`, text: badge.text }),
    // Only worth offering where there is something to open: a component
    // the project accounts for but no stage makes has nothing to edit
    (item.script || item.stage) &&
      el("a", {
        class: "small",
        text: "Edit",
        href: editUrl(
          hubWebUrl,
          link.project_owner_name,
          link.project_name,
          item,
        ),
        title: item.script
          ? `Open ${item.script} in the project`
          : `Open stage ${item.stage} in the project`,
      }),
  ]);
}

/**
 * What the paper takes from the project, and whether the reader is looking
 * at something the project still produces.
 *
 * Loaded after the sync status rather than with it: syncing is what the
 * panel is for, and this is a slower question the hub answers from the
 * document's provenance record. A paper never built with provenance on has
 * no record, and that is not a problem to report.
 */
async function renderComponents(
  body: HTMLElement,
  link: OverleafLinkPublic,
  path: string,
): Promise<void> {
  const section = el("div", { style: { marginTop: "8px" } });
  // Above the sync buttons: they are the panel's action, and nothing
  // should appear below them
  const actions = body.querySelector(".actions");
  if (actions) {
    body.insertBefore(section, actions);
  } else {
    body.append(section);
  }
  let data: PublicationComponents;
  try {
    data = await send({
      type: "project.publicationComponents",
      owner: link.project_owner_name,
      project: link.project_name,
      path,
    });
  } catch (e) {
    // A hub without the endpoint, or a document it can't place: the sync
    // panel is still useful, so this stays quiet
    if (!isUnsupportedByHub(e)) {
      section.append(
        el("div", {
          class: "dim small",
          text: "Could not check what this paper takes from the project.",
        }),
      );
    }
    return;
  }
  // The panel is about what the paper shows, not what its folder holds:
  // the file listing belongs to the hub's own components view
  const items = (data.items ?? []).filter((item) => item.kind !== "file");
  if (!data.built || items.length === 0) {
    return;
  }
  const summary = componentsSummary(items);
  section.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("div", {
          class: "small",
          style: { fontWeight: "600" },
          text: "From the project",
        }),
        el("div", {
          class: "dim small",
          text:
            `${items.length} value${items.length === 1 ? "" : "s"}, ` +
            "figures and blocks this paper shows",
        }),
      ]),
      summary
        ? el("span", { class: "badge warn", text: summary })
        : el("span", { class: "badge ok", text: "all current" }),
    ]),
    ...sortComponents(items).map((item) => componentRow(item, link)),
  );
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
    syncButton.disabled = true;
    clear(message).append(loading("Syncing"));
    try {
      const result = await send({
        type: "overleaf.sync",
        owner: link.project_owner_name,
        project: link.project_name,
        path: status.path,
      });
      clear(message).append(
        el("span", {
          class: "dim",
          text:
            `Synced. ${result.commits_from_overleaf} change` +
            `${
              result.commits_from_overleaf === 1 ? "" : "s"
            } came from Overleaf.`,
        }),
      );
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

/** Let the user point this Overleaf project at one of their Calkit projects. */
async function renderPicker(
  body: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  clear(body);
  body.append(
    el("div", {
      class: "dim small",
      text:
        "This Overleaf project isn't linked to a Calkit project yet, or the " +
        "link hasn't been seen by the hub. Pick a project to check or link.",
    }),
  );
  const search = textInput({
    placeholder: "Search your projects",
  });
  const results = el("div", { class: "stack", style: { marginTop: "6px" } });
  const message = el("div", { class: "small" });
  const checkProject = async (project: ProjectPublic) => {
    clear(message).append(loading("Checking"));
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
              `${project.name} doesn't sync with this Overleaf project. ` +
              "Import it as a new publication?",
          }),
          ...renderImportForm(project, overleafProjectId, reload),
        ]),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
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
              text: "Check",
              onClick: () => void checkProject(project),
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
  const attachContainer = el("div");
  const attachToggle = el("button", {
    class: "action secondary",
    text: "Attach to new project",
  });
  let attachOpen = false;
  attachToggle.addEventListener("click", () => {
    attachOpen = !attachOpen;
    attachToggle.textContent = attachOpen
      ? "Pick an existing project instead"
      : "Attach to new project";
    if (attachOpen) {
      void renderAttachForm(attachContainer, overleafProjectId, reload);
    } else {
      clear(attachContainer);
    }
  });
  body.append(
    search,
    results,
    message,
    el("div", { class: "actions" }, [attachToggle]),
    attachContainer,
  );
  await runSearch();
}

/**
 * Attach this Overleaf project to a Calkit project that doesn't exist yet.
 *
 * The common case is someone who already has a repo of code, data, and
 * figures and an Overleaf document written against it. Creating the
 * project around the existing repo and importing the document into a
 * folder inside it is what puts the two under one roof, after which the
 * document is a pipeline stage whose figures can be checked for
 * staleness and synced.
 */
async function renderAttachForm(
  container: HTMLElement,
  overleafProjectId: string,
  reload: () => void,
): Promise<void> {
  clear(container);
  const existsOnGithub = el("input", { type: "checkbox" });
  existsOnGithub.style.width = "auto";
  const repoInput = textInput({
    placeholder: "Start typing your GitHub repo name",
  });
  const repoResults = el("div", { class: "stack" });
  const repoFields = el("div", { class: "stack" }, [
    el("label", { text: "GitHub repo" }),
    repoInput,
    repoResults,
    el("div", {
      class: "dim small",
      text:
        "The Calkit GitHub app has to be installed for the repo you pick. " +
        "If it isn't, install it and try again.",
    }),
  ]);
  const nameInput = textInput({ placeholder: "my-project" });
  const titleInput = textInput({ placeholder: "My project" });
  const pathInput = textInput({ value: "paper" });
  const kind = el("select");
  for (const [value, label] of [
    ["journal-article", "Journal article"],
    ["conference-paper", "Conference paper"],
    ["report", "Report"],
    ["book", "Book"],
    ["masters-thesis", "Master's thesis"],
    ["phd-thesis", "PhD thesis"],
    ["other", "Other"],
  ]) {
    kind.append(el("option", { value, text: label }));
  }
  const message = el("div", { class: "small" });
  let repos: GithubRepo[] | null = null;
  let chosenRepo: GithubRepo | null = null;
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
              if (!nameInput.value.trim()) {
                nameInput.value = repo.name;
              }
              if (!titleInput.value.trim()) {
                titleInput.value = repo.name;
              }
              renderRepoResults();
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
    if (existsOnGithub.checked && repos === null) {
      void loadRepos();
    }
  };
  existsOnGithub.addEventListener("change", syncGithubFields);
  syncGithubFields();
  const attach = el("button", { class: "action", text: "Attach" });
  attach.addEventListener("click", async () => {
    attach.disabled = true;
    clear(message).append(loading("Creating the project"));
    try {
      const name = nameInput.value.trim();
      if (!name) {
        throw new Error("A project name is required");
      }
      if (existsOnGithub.checked && !chosenRepo) {
        throw new Error("Pick the GitHub repo to attach to");
      }
      const project = await send({
        type: "projects.create",
        name,
        title: titleInput.value.trim() || name,
        gitRepoUrl: chosenRepo
          ? `https://github.com/${chosenRepo.full_name}`
          : undefined,
        isPublic: false,
      });
      clear(message).append(loading("Importing the Overleaf project"));
      await send({
        type: "overleaf.import",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: pathInput.value.trim() || "paper",
        kind: kind.value,
      });
      reload();
    } catch (e) {
      attach.disabled = false;
      clear(message).append(renderFailure(e, { onSignedIn: reload }));
    }
  });
  container.append(
    el("label", { class: "row", style: { fontWeight: "400" } }, [
      existsOnGithub,
      el("div", { class: "grow small", text: "Exists on GitHub" }),
    ]),
    repoFields,
    el("label", { text: "Project name" }),
    nameInput,
    el("label", { text: "Title" }),
    titleInput,
    el("label", { text: "Folder for the Overleaf project" }),
    pathInput,
    el("div", {
      class: "dim small",
      text: "Where the document lives inside the larger project.",
    }),
    el("label", { text: "Type" }),
    kind,
    el("div", { class: "actions" }, [attach]),
    message,
  );
}

function renderImportForm(
  project: ProjectPublic,
  overleafProjectId: string,
  reload: () => void,
): HTMLElement[] {
  const path = textInput({
    value: "paper",
  });
  const kind = el("select");
  for (const [value, label] of [
    ["journal-article", "Journal article"],
    ["conference-paper", "Conference paper"],
    ["report", "Report"],
    ["book", "Book"],
    ["masters-thesis", "Master's thesis"],
    ["phd-thesis", "PhD thesis"],
    ["other", "Other"],
  ]) {
    kind.append(el("option", { value, text: label }));
  }
  const importButton = el("button", {
    class: "action",
    text: "Import and link",
  });
  const message = el("div", { class: "small" });
  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    clear(message).append(loading("Importing"));
    try {
      await send({
        type: "overleaf.import",
        owner: project.owner_account_name,
        project: project.name,
        overleafProjectUrl: `https://www.overleaf.com/project/${overleafProjectId}`,
        path: path.value.trim(),
        kind: kind.value,
      });
      reload();
    } catch (e) {
      importButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  return [
    el("label", { text: "Folder in the project" }),
    path,
    el("label", { text: "Type" }),
    kind,
    el("div", { class: "actions" }, [importButton]),
    message,
  ];
}

async function load(overleafProjectId: string): Promise<void> {
  if (!panel) {
    return;
  }
  const body = panel.body;
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
    clear(body).append(pickers, loading("Looking for the linked project"));
    // The index answers at once when this Overleaf project has been seen
    // before; otherwise the hub reads through the user's projects, active
    // one first, and remembers what it finds
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    const links = lookup.links;
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
    clear(body).append(pickers);
    const content = el("div");
    body.append(content);
    // A folder in more than one project is rare, so the first link is the
    // one shown, with the rest offered as alternatives underneath
    const link = links[0];
    clear(content).append(
      loading(`Checking ${link.project_owner_name}/${link.project_name}`),
    );
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    });
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
    lastSyncNeeded = !statuses[0].in_sync;
    renderStatus(content, link, statuses[0], reload);
    // After the sync status, since that is what the panel is for and this
    // is the slower question
    void renderComponents(content, link, statuses[0].path);
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
    const message = e instanceof Error ? e.message : String(e);
    body.append(errorMessage(message));
    if (message.includes("Overleaf token")) {
      body.append(
        el("div", { class: "dim small", style: { marginTop: "6px" } }, [
          document.createTextNode("Connect Overleaf in your "),
          el("a", {
            text: "Calkit account settings",
            href: `${hubWebUrl}/settings?tab=connected-accounts`,
          }),
          document.createTextNode(" to check sync status."),
        ]),
      );
    }
  }
}

/**
 * The button that opens the panel, and what it collapses back to.
 *
 * Its tone carries the one thing worth interrupting for: amber means a
 * sync would do something, which is how a stale figure gets noticed
 * without the panel opening on top of the document uninvited.
 */
type LauncherTone = "idle" | "attention";

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
    text: tone === "attention" ? "Calkit: sync needed" : "Calkit",
    class: tone === "attention" ? "attention" : "",
  });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

// Remembered so a closed panel can still show that something is waiting
let lastSyncNeeded = false;

function openPanel(overleafProjectId: string): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  panel = mountPanel({
    id: PANEL_ID,
    title: "Calkit",
    onClose: () => {
      panel = null;
      mountLauncher(
        () => openPanel(overleafProjectId),
        lastSyncNeeded ? "attention" : "idle",
      );
    },
  });
  void load(overleafProjectId);
}

function teardown(): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  panel?.remove();
  panel = null;
  currentProjectId = null;
}

function sync(): void {
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
  try {
    const settings = await send({ type: "settings.get" });
    const lookup = await send({
      type: "overleaf.lookup",
      overleafProjectId,
      activeProject: settings.activeProject ?? undefined,
    });
    const link = lookup.links[0];
    if (!link) {
      return;
    }
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    });
    lastSyncNeeded = Boolean(statuses.length) && !statuses[0].in_sync;
    // Nothing to say if the panel was opened in the meantime, or if the
    // page moved on to another project
    if (panel || currentProjectId !== overleafProjectId) {
      return;
    }
    if (lastSyncNeeded) {
      mountLauncher(() => openPanel(overleafProjectId), "attention");
    }
  } catch {
    // Whatever went wrong, the panel says so properly when opened
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
runContentScript({ id: "overleaf", sync, teardown });
