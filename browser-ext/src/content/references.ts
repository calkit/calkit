import {
  detectReference,
  suggestCitationKey,
  type DetectedReference,
} from "../core/detect";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import { runContentScript } from "../core/lifecycle";
import { RequestFailed, send } from "../core/messages";
import {
  renderFailure,
  renderHubPicker,
  renderProjectPicker,
} from "../core/pickers";
import type { ReferenceNote, ReferenceSearchMatch } from "../core/types";
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

const PANEL_ID = "calkit-reference-panel";
const LAUNCHER_ID = "calkit-reference-launcher";
// Where a project's first references collection goes, and the offer
// made alongside any it already has. The hub creates it on first add.
const ROOT_BIB = "references.bib";

let panel: Panel | null = null;
let hubWebUrl = "https://calkit.io";
let launcher: LauncherHandle | null = null;

interface LauncherHandle {
  setLabel: (label: string, tone: "neutral" | "match" | "none") => void;
}

function mountLauncher(onClick: () => void): LauncherHandle {
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

/**
 * Say on the button what the last lookup found.
 *
 * Called from the panel as well as on load, because the load-time lookup
 * can't answer at all when no project is active yet, and picking one in
 * the panel is exactly when the answer arrives. Reading the module-level
 * launcher rather than closing over one keeps a stale lookup from writing
 * to a button that has since been replaced.
 */
function showMatchCount(matches: ReferenceSearchMatch[]): void {
  if (!launcher) {
    return;
  }
  if (matches.length) {
    launcher.setLabel(
      `In ${matches.length} collection${matches.length === 1 ? "" : "s"}`,
      "match",
    );
  } else {
    launcher.setLabel("Add to Calkit", "none");
  }
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
  /** Where this reference already is, so it isn't filed twice. */
  matches: ReferenceSearchMatch[] = [],
): Promise<void> {
  clear(container);
  if (!activeProject) {
    container.append(
      el("div", {
        class: "dim small",
        text: "Pick an active project above to add this reference to it.",
      }),
    );
    return;
  }
  const collectionSelect = el("select");
  const keyInput = textInput({
    value: suggestCitationKey(reference),
  });
  const message = el("div", { class: "small" });
  const addButton = el("button", {
    class: "action",
    text: "Add to collection",
  });
  const [owner, name] = activeProject.split("/");
  const collectionStatus = el("div", { class: "small" });
  // Collections in this project that already hold this reference. Adding
  // it again would either 409 or quietly duplicate the entry, so the
  // option is disabled rather than offered and then refused.
  const alreadyIn = new Set(
    matches
      .filter(
        (match) =>
          `${match.project_owner_name}/${match.project_name}` === activeProject,
      )
      .map((match) => match.path),
  );
  const syncAddState = () => {
    const taken = alreadyIn.has(collectionSelect.value);
    addButton.disabled = taken;
    addButton.title = taken
      ? "This reference is already in that collection"
      : "";
    if (taken) {
      clear(message).append(
        el("span", {
          class: "dim",
          text: "Already in this collection. Pick another, or a different project.",
        }),
      );
    }
  };
  collectionSelect.addEventListener("change", syncAddState);
  const loadCollections = async () => {
    clear(collectionSelect);
    // Reading a project's collections means reading its repo, which takes
    // a moment, so the form says so instead of showing an empty select
    // next to an Add button that would post nothing
    collectionSelect.disabled = true;
    addButton.disabled = true;
    clear(collectionStatus).append(loading("Loading collections"));
    try {
      const collections = await send({
        type: "references.list",
        owner,
        project: name,
      });
      if (!collections.length) {
        collectionSelect.append(
          el("option", { value: ROOT_BIB, text: `${ROOT_BIB} (new)` }),
        );
        return;
      }
      for (const collection of collections) {
        collectionSelect.append(
          el("option", { value: collection.path, text: collection.path }),
        );
      }
      // A project with collections can still want a new root-level one
      if (!collections.some((collection) => collection.path === ROOT_BIB)) {
        collectionSelect.append(
          el("option", { value: ROOT_BIB, text: `${ROOT_BIB} (new)` }),
        );
      }
    } catch (e) {
      // Listing collections is only how the options get filled in. Adding
      // to a root-level references.bib still works, and creates it, so a
      // failure here shouldn't leave the form with nothing to submit.
      collectionSelect.append(
        el("option", { value: ROOT_BIB, text: `${ROOT_BIB} (new)` }),
      );
      clear(message).append(renderFailure(e, { onSignedIn: reload }));
    } finally {
      clear(collectionStatus);
      collectionSelect.disabled = false;
      addButton.disabled = false;
      syncAddState();
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
    el("label", { text: "Collection" }),
    collectionSelect,
    collectionStatus,
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
    const [hubPicker, projectPicker] = await Promise.all([
      renderHubPicker(reload),
      renderProjectPicker({
        activeProject: settings.activeProject,
        onChange: reload,
      }),
    ]);
    clear(body).append(
      referenceSummary(reference),
      el("div", { class: "muted-box stack", style: { marginTop: "8px" } }, [
        hubPicker,
        projectPicker,
      ]),
    );
    // Whether this reference is already filed is useful to know, but it is
    // not what the panel is for. A lookup that fails, including against a
    // hub too old to offer the search, leaves adding and switching
    // projects working rather than replacing the panel with an error.
    let matches: ReferenceSearchMatch[] = [];
    let lookupError: string | null = null;
    try {
      matches = await searchMatches(reference, settings.activeProject);
      // The button asked the same question on load, but couldn't answer
      // without an active project, and this is where one gets picked
      if (settings.activeProject) {
        showMatchCount(matches);
      }
    } catch (e) {
      // Signing in is the whole panel's problem, not this one lookup's
      if (e instanceof RequestFailed && e.notSignedIn) {
        throw e;
      }
      lookupError = e instanceof Error ? e.message : String(e);
    }
    if (matches.length) {
      body.append(
        el("div", {
          class: "small",
          style: { marginTop: "8px", fontWeight: "600" },
          text: "Already in your collections",
        }),
        ...matches.map(matchRow),
      );
    } else if (lookupError) {
      body.append(
        el("div", { class: "dim small", style: { marginTop: "8px" } }, [
          document.createTextNode(
            `Couldn't check whether this is already filed (${lookupError}). `,
          ),
          document.createTextNode("You can still add it below."),
        ]),
      );
    } else {
      body.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "8px" },
          text: settings.activeProject
            ? `Not in any collection in ${settings.activeProject}.`
            : "Pick a project above to check it.",
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
      matches,
    );
  } catch (e) {
    const failure = renderFailure(e, {
      hubUrl: hubWebUrl,
      onSignedIn: reload,
    });
    clear(body).append(referenceSummary(reference), failure);
    // The picker asks the worker which hubs exist, so it is the one thing
    // that cannot be relied on here: when the worker is what failed, it
    // fails too. Saying what went wrong comes first, and the picker goes in
    // above it only if it can be built
    try {
      body.insertBefore(await renderHubPicker(reload), failure);
    } catch {
      // Whatever renderFailure already says is the more useful message
    }
  }
}

async function start(): Promise<void> {
  const reference = detectReference();
  if (!reference) {
    return;
  }
  launcher = mountLauncher(() => void openPanel(reference));
  // One lookup on load tells the user whether this paper is already in a
  // collection without them having to open anything
  try {
    const settings = await send({ type: "settings.get" });
    if (!settings.activeProject) {
      // Nothing to look in yet. The panel updates the button if the user
      // picks a project there, so this stays neutral rather than claiming
      // the paper isn't filed anywhere
      return;
    }
    showMatchCount(await searchMatches(reference, settings.activeProject));
  } catch {
    // A failed lookup, e.g. nobody signed in, just leaves the neutral label
  }
}

runContentScript({
  id: "references",
  sync: () => void start(),
  teardown: () => {
    document.getElementById(LAUNCHER_ID)?.remove();
    panel?.remove();
    panel = null;
  },
});
