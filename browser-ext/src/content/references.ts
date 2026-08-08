import {
  detectReference,
  suggestCitationKey,
  type DetectedReference,
} from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { RequestFailed, send } from "../core/messages";
import type { ReferenceNote, ReferenceSearchMatch } from "../core/types";
import {
  clear,
  el,
  errorMessage,
  loading,
  mountPanel,
  signInPrompt,
  type Panel,
} from "../core/ui";

const PANEL_ID = "calkit-reference-panel";
const LAUNCHER_ID = "calkit-reference-launcher";

let panel: Panel | null = null;
let hubWebUrl = "https://calkit.io";

interface LauncherHandle {
  setLabel: (label: string, tone: "neutral" | "match" | "none") => void;
}

function mountLauncher(onClick: () => void): LauncherHandle {
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
      background: #718096;
      border: 0;
      border-radius: 999px;
      padding: 8px 14px;
      cursor: pointer;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    }
    button.match { background: #009688; }
    button.none { background: #718096; }
    button:hover { filter: brightness(1.1); }
  `;
  const button = el("button", { text: "Calkit" });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
  return {
    setLabel: (label, tone) => {
      button.textContent = label;
      button.className = tone === "neutral" ? "" : tone;
    },
  };
}

function referenceSummary(reference: DetectedReference): HTMLElement {
  const identifier = reference.doi
    ? `doi:${reference.doi}`
    : reference.arxivId
    ? `arXiv:${reference.arxivId}`
    : "no identifier found";
  return el("div", { class: "muted-box stack" }, [
    el("div", { text: reference.title ?? "Untitled" }),
    el("div", { class: "dim small", text: identifier }),
    reference.authors
      ? el("div", { class: "dim small", text: reference.authors })
      : null,
  ]);
}

async function renderNotes(
  container: HTMLElement,
  match: ReferenceSearchMatch,
): Promise<void> {
  clear(container).append(loading("Loading notes"));
  let notes: ReferenceNote[];
  try {
    notes = (
      await send({
        type: "references.notes.get",
        owner: match.project_owner_name,
        project: match.project_name,
        path: match.path,
        bibKey: match.key,
      })
    ).notes;
  } catch (e) {
    clear(container).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
    return;
  }
  clear(container);
  const editors: HTMLTextAreaElement[] = [];
  const list = el("div", { class: "stack" });
  const addEditor = (text: string) => {
    const editor = el("textarea", { value: text });
    editors.push(editor);
    list.append(editor);
  };
  for (const note of notes) {
    addEditor(note.text);
  }
  if (!notes.length) {
    addEditor("");
  }
  const message = el("div", { class: "small" });
  const save = el("button", { class: "action", text: "Save notes" });
  save.addEventListener("click", async () => {
    save.disabled = true;
    clear(message).append(loading("Saving"));
    try {
      const updated = await send({
        type: "references.notes.put",
        owner: match.project_owner_name,
        project: match.project_name,
        path: match.path,
        bibKey: match.key,
        notes: editors
          .map((editor) => editor.value.trim())
          .filter(Boolean)
          .map((text) => ({ text })),
      });
      clear(message).append(
        el("span", {
          class: "dim",
          text: `Saved ${updated.notes.length} note${
            updated.notes.length === 1 ? "" : "s"
          }.`,
        }),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    } finally {
      save.disabled = false;
    }
  });
  container.append(
    list,
    el("div", { class: "actions" }, [
      save,
      el("button", {
        class: "action secondary",
        text: "Add another",
        onClick: () => addEditor(""),
      }),
    ]),
    message,
  );
}

function matchRow(match: ReferenceSearchMatch): HTMLElement {
  const notesContainer = el("div", { style: { marginTop: "6px" } });
  const notesButton = el("button", {
    class: "action secondary",
    text: match.note_count ? `Notes (${match.note_count})` : "Notes",
  });
  let notesOpen = false;
  notesButton.addEventListener("click", () => {
    notesOpen = !notesOpen;
    if (notesOpen) {
      void renderNotes(notesContainer, match);
    } else {
      clear(notesContainer);
    }
  });
  return el("div", { style: { padding: "5px 0" } }, [
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("a", {
          text: `${match.project_owner_name}/${match.project_name}`,
          href: projectUrl(
            hubWebUrl,
            match.project_owner_name,
            match.project_name,
          ),
        }),
        el("div", { class: "dim small", text: `${match.path} · ${match.key}` }),
      ]),
      notesButton,
    ]),
    notesContainer,
  ]);
}

function bibFields(reference: DetectedReference): Record<string, string> {
  const fields: Record<string, string> = {};
  if (reference.title) fields.title = reference.title;
  if (reference.authors) fields.author = reference.authors;
  if (reference.year) fields.year = reference.year;
  if (reference.journal) fields.journal = reference.journal;
  if (reference.doi) fields.doi = reference.doi;
  if (reference.arxivId) {
    fields.eprint = reference.arxivId;
    fields.archiveprefix = "arXiv";
  }
  fields.url = reference.url;
  return fields;
}

async function renderAddForm(
  container: HTMLElement,
  reference: DetectedReference,
  activeProject: string | null,
  reload: () => void,
): Promise<void> {
  clear(container);
  if (!activeProject) {
    container.append(
      el("div", { class: "dim small" }, [
        document.createTextNode("Choose an active project in the "),
        el("a", {
          text: "extension options",
          href: chrome.runtime.getURL("options.html"),
        }),
        document.createTextNode(" to add references to it."),
      ]),
    );
    return;
  }
  const collectionSelect = el("select");
  const keyInput = el("input", {
    type: "text",
    value: suggestCitationKey(reference),
    attrs: { autocomplete: "off", "data-lpignore": "true" },
  });
  const message = el("div", { class: "small" });
  const addButton = el("button", {
    class: "action",
    text: "Add to collection",
  });
  const [owner, name] = activeProject.split("/");
  const loadCollections = async () => {
    clear(collectionSelect);
    try {
      const collections = await send({
        type: "references.list",
        owner,
        project: name,
      });
      if (!collections.length) {
        collectionSelect.append(
          el("option", {
            value: "references.bib",
            text: "references.bib (new)",
          }),
        );
        return;
      }
      for (const collection of collections) {
        collectionSelect.append(
          el("option", { value: collection.path, text: collection.path }),
        );
      }
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  addButton.addEventListener("click", async () => {
    addButton.disabled = true;
    clear(message).append(loading("Adding"));
    try {
      await send({
        type: "references.add",
        owner,
        project: name,
        path: collectionSelect.value,
        key: keyInput.value.trim(),
        entryType: reference.arxivId && !reference.doi ? "misc" : "article",
        fields: bibFields(reference),
      });
      reload();
    } catch (e) {
      addButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  container.append(
    el("label", { text: "Project" }),
    el("div", { class: "small", text: activeProject }),
    el("label", { text: "Collection" }),
    collectionSelect,
    el("label", { text: "Citation key" }),
    keyInput,
    el("div", { class: "actions" }, [addButton]),
    message,
  );
  await loadCollections();
}

async function searchMatches(
  reference: DetectedReference,
  activeProject: string | null,
): Promise<ReferenceSearchMatch[]> {
  if (!activeProject) {
    return [];
  }
  if (!reference.doi && !reference.arxivId && !reference.title) {
    return [];
  }
  return send({
    type: "references.search",
    projects: [activeProject],
    doi: reference.doi ?? undefined,
    arxivId: reference.arxivId ?? undefined,
    title: reference.title ?? undefined,
  });
}

async function openPanel(reference: DetectedReference): Promise<void> {
  panel = mountPanel({ id: PANEL_ID, title: "Calkit reference" });
  const body = panel.body;
  const reload = () => void openPanel(reference);
  clear(body).append(referenceSummary(reference), loading());
  try {
    hubWebUrl = await getHubWebUrl();
    const settings = await send({ type: "settings.get" });
    const matches = await searchMatches(reference, settings.activeProject);
    clear(body).append(referenceSummary(reference));
    if (matches.length) {
      body.append(
        el("div", {
          class: "small",
          style: { marginTop: "8px", fontWeight: "600" },
          text: "Already in your collections",
        }),
        ...matches.map(matchRow),
      );
    } else {
      body.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "8px" },
          text: settings.activeProject
            ? `Not in any collection in ${settings.activeProject}.`
            : "No active project is set yet.",
        }),
      );
    }
    const addContainer = el("div", { style: { marginTop: "8px" } });
    body.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Add this reference",
      }),
      addContainer,
    );
    await renderAddForm(
      addContainer,
      reference,
      settings.activeProject,
      reload,
    );
  } catch (e) {
    clear(body).append(referenceSummary(reference));
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

async function start(): Promise<void> {
  const reference = detectReference();
  if (!reference) {
    return;
  }
  const launcher = mountLauncher(() => void openPanel(reference));
  // One lookup on load tells the user whether this paper is already in a
  // collection without them having to open anything
  try {
    const settings = await send({ type: "settings.get" });
    if (!settings.activeProject) {
      return;
    }
    const matches = await searchMatches(reference, settings.activeProject);
    if (matches.length) {
      launcher.setLabel(
        `In ${matches.length} collection${matches.length === 1 ? "" : "s"}`,
        "match",
      );
    } else {
      launcher.setLabel("Add to Calkit", "none");
    }
  } catch {
    // A failed lookup, e.g. nobody signed in, just leaves the neutral label
  }
}

void start();
