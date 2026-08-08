import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { RequestFailed, send } from "../core/messages";
import type { ProjectPublic, References, ZoteroLibrary } from "../core/types";
import {
  clear,
  el,
  errorMessage,
  loading,
  mountPanel,
  signInPrompt,
  type Panel,
  textInput,
} from "../core/ui";

const PANEL_ID = "calkit-zotero-panel";
const LAUNCHER_ID = "calkit-zotero-launcher";

let panel: Panel | null = null;
let hubWebUrl = "https://calkit.io";

/** Whether this page is a Zotero web library, rather than zotero.org at large. */
function isLibraryPage(): boolean {
  return /^\/(mylibrary|groups\/\d+|[^/]+\/(items|collections))/.test(
    window.location.pathname,
  );
}

function mountLauncher(onClick: () => void): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  const host = el("div", { attrs: { id: LAUNCHER_ID } });
  Object.assign(host.style, {
    position: "fixed",
    right: "16px",
    bottom: "16px",
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
    button:hover { background: #00766c; }
  `;
  const button = el("button", { text: "Calkit" });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

/** Existing Zotero-linked collections in the project, with a sync action. */
function linkedCollections(
  project: ProjectPublic,
  collections: References[],
): HTMLElement {
  const linked = collections.filter((c) => c.zotero);
  const container = el("div", { class: "stack" });
  if (!linked.length) {
    container.append(
      el("div", {
        class: "dim small",
        text: "No collections in this project are linked to Zotero yet.",
      }),
    );
    return container;
  }
  for (const collection of linked) {
    const message = el("div", { class: "small" });
    const syncButton = el("button", {
      class: "action secondary",
      text: "Sync",
    });
    syncButton.addEventListener("click", async () => {
      syncButton.disabled = true;
      clear(message).append(loading("Syncing"));
      try {
        const result = await send({
          type: "zotero.sync",
          owner: project.owner_account_name,
          project: project.name,
          path: collection.path,
        });
        clear(message).append(
          el("span", {
            class: "dim",
            text: result.committed
              ? "Synced and committed."
              : "Synced; nothing changed.",
          }),
        );
      } catch (e) {
        clear(message).append(
          errorMessage(e instanceof Error ? e.message : String(e)),
        );
      } finally {
        syncButton.disabled = false;
      }
    });
    container.append(
      el("div", {}, [
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", { class: "name", text: collection.path }),
            el("div", {
              class: "dim small",
              text:
                collection.zotero?.collection_name ??
                collection.zotero?.collection_key ??
                "",
            }),
          ]),
          syncButton,
        ]),
        message,
      ]),
    );
  }
  return container;
}

async function renderImport(
  container: HTMLElement,
  project: ProjectPublic,
  reload: () => void,
): Promise<void> {
  clear(container).append(loading("Reading your Zotero libraries"));
  let libraries: ZoteroLibrary[];
  try {
    libraries = await send({
      type: "zotero.libraries",
      owner: project.owner_account_name,
      project: project.name,
    });
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    clear(container).append(errorMessage(message));
    container.append(
      el("div", { class: "dim small", style: { marginTop: "6px" } }, [
        document.createTextNode("Connect Zotero in your "),
        el("a", {
          text: "Calkit account settings",
          href: `${hubWebUrl}/settings?tab=connected-accounts`,
        }),
        document.createTextNode(" to import collections."),
      ]),
    );
    return;
  }
  clear(container);
  const librarySelect = el("select");
  for (const library of libraries) {
    librarySelect.append(
      el("option", {
        value: `${library.library_type}:${library.library_id}`,
        text: library.name,
      }),
    );
  }
  const collectionSelect = el("select");
  const bibPath = textInput({
    value: "references.bib",
  });
  const message = el("div", { class: "small" });
  const loadCollections = async () => {
    clear(collectionSelect);
    const [libraryType, libraryId] = librarySelect.value.split(":");
    try {
      const collections = await send({
        type: "zotero.collections",
        owner: project.owner_account_name,
        project: project.name,
        libraryType: libraryType as "user" | "group",
        libraryId,
      });
      for (const collection of collections) {
        collectionSelect.append(
          el("option", {
            value: collection.collection_key,
            text: collection.collection_name ?? collection.collection_key,
          }),
        );
      }
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  librarySelect.addEventListener("change", () => void loadCollections());
  const importButton = el("button", { class: "action", text: "Import" });
  importButton.addEventListener("click", async () => {
    importButton.disabled = true;
    clear(message).append(loading("Importing"));
    const [libraryType, libraryId] = librarySelect.value.split(":");
    try {
      await send({
        type: "zotero.import",
        owner: project.owner_account_name,
        project: project.name,
        libraryType: libraryType as "user" | "group",
        libraryId,
        collectionKey: collectionSelect.value,
        bibPath: bibPath.value.trim(),
      });
      reload();
    } catch (e) {
      importButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("label", { text: "Zotero library" }),
    librarySelect,
    el("label", { text: "Collection" }),
    collectionSelect,
    el("label", { text: "Write to" }),
    bibPath,
    el("div", { class: "actions" }, [importButton]),
    message,
  );
  await loadCollections();
}

async function renderProject(
  body: HTMLElement,
  project: ProjectPublic,
  reload: () => void,
): Promise<void> {
  clear(body).append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${project.owner_account_name}/${project.name}`,
          href: projectUrl(hubWebUrl, project.owner_account_name, project.name),
        }),
        el("div", { class: "dim small", text: project.title }),
      ]),
      el("button", {
        class: "action secondary",
        text: "Change",
        onClick: reload,
      }),
    ]),
  );
  const linkedContainer = el("div", { style: { marginTop: "8px" } });
  body.append(
    el("div", {
      class: "small",
      style: { fontWeight: "600" },
      text: "Linked collections",
    }),
    linkedContainer,
  );
  clear(linkedContainer).append(loading());
  try {
    const collections = await send({
      type: "references.list",
      owner: project.owner_account_name,
      project: project.name,
    });
    clear(linkedContainer).append(linkedCollections(project, collections));
  } catch (e) {
    clear(linkedContainer).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
  const importContainer = el("div", { style: { marginTop: "8px" } });
  body.append(
    el("div", {
      class: "small",
      style: { fontWeight: "600", marginTop: "8px" },
      text: "Import a collection",
    }),
    importContainer,
  );
  await renderImport(importContainer, project, reload);
}

async function openPanel(): Promise<void> {
  panel = mountPanel({ id: PANEL_ID, title: "Calkit" });
  const body = panel.body;
  const reload = () => void openPanel();
  clear(body).append(loading());
  try {
    hubWebUrl = await getHubWebUrl();
    const settings = await send({ type: "settings.get" });
    const projects = await send({ type: "projects.list", limit: 100 });
    clear(body);
    if (!projects.data.length) {
      body.append(el("div", { class: "dim small", text: "No projects yet." }));
      return;
    }
    // Go straight into the active project, which is where a collection is
    // almost always headed; the list is there for the exceptions
    const active = projects.data.find(
      (project) =>
        `${project.owner_account_name}/${project.name}` ===
        settings.activeProject,
    );
    if (active) {
      await renderProject(body, active, reload);
      return;
    }
    body.append(
      el("div", {
        class: "dim small",
        text: "Pick the project to import into or sync with.",
      }),
    );
    for (const project of projects.data.slice(0, 25)) {
      body.append(
        el("div", { class: "row" }, [
          el("div", { class: "grow" }, [
            el("div", {
              text: `${project.owner_account_name}/${project.name}`,
            }),
            el("div", { class: "dim small", text: project.title }),
          ]),
          el("button", {
            class: "action secondary",
            text: "Open",
            onClick: () => void renderProject(body, project, reload),
          }),
        ]),
      );
    }
  } catch (e) {
    clear(body);
    if (e instanceof RequestFailed && e.notSignedIn) {
      body.append(
        signInPrompt(async () => {
          try {
            await send({ type: "auth.signIn" });
            reload();
          } catch (signInError) {
            body.append(
              errorMessage(
                signInError instanceof Error
                  ? signInError.message
                  : String(signInError),
              ),
            );
          }
        }),
      );
      return;
    }
    body.append(errorMessage(e instanceof Error ? e.message : String(e)));
  }
}

runContentScript({
  id: "zotero",
  sync: () => {
    if (isLibraryPage()) {
      mountLauncher(() => void openPanel());
    }
  },
  teardown: () => {
    document.getElementById(LAUNCHER_ID)?.remove();
    panel?.remove();
    panel = null;
  },
});
