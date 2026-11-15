import { getOverleafProjectId } from "../core/detect";
import calkitLogo from "../../public/icons/calkit.svg?raw";
import {
  renderFailure,
  renderHubPicker,
  renderPathPicker,
  renderProjectPicker,
} from "../core/pickers";
import { getHubWebUrl, projectUrl } from "../core/hub-url";
import {
  getEditorLabel,
  getGitBlobSha,
  type CheckoutStatus,
  type LocalStatus,
} from "../core/local";
import {
  type Citation,
  type CitationProblem,
  canBeCreatedByPerson,
  citationProblems,
  citationText,
  getShownValue,
  citationCandidates,
} from "../core/latex";
import { runContentScript } from "../core/lifecycle";
import {
  isExtensionAlive,
  isUnsupportedByHub,
  type Request,
  RequestFailed,
  send,
} from "../core/messages";
import type {
  GithubRepo,
  OverleafLinkPublic,
  Provenance,
  StageFromScriptOrNotebookResponse,
  OverleafSyncResponse,
  OverleafSyncStatus,
  OverleafSyncStatusFile,
  PipelineRun,
  PipelineRuns,
  ProjectPipeline,
  ProjectPublic,
} from "../core/types";
import {
  clear,
  el,
  launcherPosition,
  errorMessage,
  loading,
  mountOverlay,
  mountPanel,
  type Panel,
  STYLES,
  textInput,
} from "../core/ui";
import {
  type CommentAuthor,
  type FromReview,
  type LineEdit,
  type OverleafComment,
  type OverleafSynced,
  type OverleafThread,
  type PdfRect,
  type ToReview,
  findParagraphByText,
  getAddEdit,
  getEditedLines,
  getOverleafSyncedLines,
  getReply,
  getReviewThreads,
  getThreadEdit,
} from "../core/review";
import { getZipTexts } from "../core/zip";
import { type PdfBox, placePdfBoxes } from "../core/pdf-boxes";
import {
  findInSource,
  lineMap,
  paragraphLines,
} from "../../../vscode-ext/src/latex/core";
import type { EditorCitation, FromEditor, ToEditor } from "./overleaf-editor";

const PANEL_ID = "calkit-overleaf-panel";
const LAUNCHER_ID = "calkit-overleaf-launcher";
const TOKEN_PANEL_ID = "calkit-overleaf-token-panel";
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
// The Calkit project this Overleaf project syncs with, once found
let currentLink: OverleafLinkPublic | null = null;
// Kept for a minute, since the project changes under it, e.g., with a sync
const provenanceCache = new Map<
  string,
  { at: number; provenance: Promise<Provenance> }
>();

function provenanceFor(
  link: OverleafLinkPublic,
  path: string,
  key?: string,
): Promise<Provenance> {
  const cacheKey = `${link.project_owner_name}/${link.project_name}:${path}:${
    key ?? ""
  }`;
  const cached = provenanceCache.get(cacheKey);
  if (cached && Date.now() - cached.at < 60_000) {
    return cached.provenance;
  }
  const provenance = send({
    type: "project.provenance",
    owner: link.project_owner_name,
    project: link.project_name,
    path,
    key,
  });
  // A failure is worth asking again about next time
  provenance.catch(() => provenanceCache.delete(cacheKey));
  provenanceCache.set(cacheKey, { at: Date.now(), provenance });
  return provenance;
}

/**
 * Where a file the document shows came from, finding it in the project
 * first, since TeX may find it under a name with an extension added, and
 * finds a plainly included one relative to the document.
 */
async function citationProvenance(
  link: OverleafLinkPublic,
  citation: Citation,
): Promise<Provenance> {
  if (citation.kind === "value") {
    return provenanceFor(link, citation.path, citation.key);
  }
  const candidates = citationCandidates(link.path, citation);
  let first: Provenance | null = null;
  for (const candidate of candidates) {
    const provenance = await provenanceFor(link, candidate);
    if (provenance.exists) {
      return provenance;
    }
    first ??= provenance;
  }
  return first ?? provenanceFor(link, candidates[0]);
}

/**
 * Type into Overleaf's editor at the cursor, as if the user had.
 *
 * CodeMirror keeps its selection while the panel has focus and puts it
 * back when the editor is focused again, and it handles an insertText
 * command like typing, so the edit lands in Overleaf's history and syncs.
 * Falls back to the clipboard when there's no editor to type into, e.g.,
 * with a PDF open instead of a .tex file.
 */
async function insertIntoEditor(text: string): Promise<"inserted" | "copied"> {
  const editor = document.querySelector<HTMLElement>(".cm-content");
  if (editor) {
    editor.focus();
    if (document.execCommand("insertText", false, text)) {
      return "inserted";
    }
  }
  await navigator.clipboard.writeText(text);
  return "copied";
}

/** All the data that can be uploaded with a script, as the hub allows. */
const MAX_SCRIPT_DATA_BYTES = 50_000_000;

/** A value as it reads in a panel row. */
function valueText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * Make the stage that produces what the document shows, from the script
 * that makes it, uploaded or already in the project.
 *
 * The hub reads the script the way `calkit xr --dry-run` does, without
 * running it, so the user sees the environment, inputs, and outputs before
 * anything is committed. Overleaf can't run it, so once it's saved the
 * panel says how to, on the user's own computer.
 */
function renderAddScript(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
  shows: string,
  kind: "script" | "notebook",
): HTMLElement {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const exts =
    kind === "notebook" ? [".ipynb"] : [".py", ".r", ".jl", ".m", ".sh"];
  const file = el("input", {
    type: "file",
    attrs: { accept: exts.join(",") },
  });
  const { element: picker, input: path } = renderPathPicker({
    owner,
    project,
    placeholder: "Or find it in the project",
    accept: (p) => exts.some((ext) => p.toLowerCase().endsWith(ext)),
  });
  const read = el("button", { class: "action", text: `Read the ${kind}` });
  const message = el("div", { class: "small" });
  const review = el("div", { class: "stack", style: { marginTop: "6px" } });
  let request: {
    scriptPath: string;
    content?: string;
  } | null = null;
  // Data the script reads from outside the project, by how it names it,
  // and the files that go in the project in its place
  const data = new Map<
    string,
    { path: string; files: { path: string; file: File }[] }
  >();
  // Contents are only read to save; until then, where it goes is enough to
  // see the script read it from there
  const dataRequest = (withContent: boolean) =>
    Promise.all(
      [...data].map(async ([external, { path, files }]) => ({
        external,
        path,
        files: withContent
          ? await Promise.all(
              files.map(async (f) => ({
                path: f.path,
                content: await fileBase64(f.file),
              })),
            )
          : [],
      })),
    );
  const reread = async () => {
    if (!request) {
      return;
    }
    const detected = await send({
      type: "project.stageFromScriptOrNotebook",
      owner,
      project,
      ...request,
      shows,
      data: await dataRequest(false),
    });
    clear(message);
    clear(review);
    renderReview(detected);
  };
  const fail = (e: unknown) =>
    clear(message).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  read.addEventListener("click", async () => {
    clear(message);
    clear(review);
    const upload = file.files?.[0];
    const typed = path.value.trim();
    if (!upload && !typed) {
      fail(`Choose the ${kind}, or find it in the project.`);
      return;
    }
    read.disabled = true;
    message.append(loading("Reading"));
    data.clear();
    try {
      request = upload
        ? {
            // An upload goes where it's named, or with others of its kind
            scriptPath: typed || `${kind}s/${upload.name}`,
            content: await fileBase64(upload),
          }
        : { scriptPath: typed };
      await reread();
    } catch (e) {
      fail(e);
    } finally {
      read.disabled = false;
    }
  });
  // Where data from outside the project goes in it, uploaded from this
  // computer, which is likely the one the script ran on
  const renderExternal = (
    external: string,
    detected: StageFromScriptOrNotebookResponse,
  ) => {
    const chosen = data.get(external);
    const name = external.split(/[\\/]/).filter(Boolean).pop() ?? "data";
    const dest = textInput({ value: chosen?.path ?? `data/${name}` });
    const files = el("input", {
      type: "file",
      attrs: { multiple: "" },
      style: { display: "none" },
    });
    const folder = el("input", {
      type: "file",
      attrs: { webkitdirectory: "" },
      style: { display: "none" },
    });
    const pickFiles = el("button", {
      class: "action secondary",
      text: "Choose files",
    });
    const pickFolder = el("button", {
      class: "action secondary",
      text: "Choose a folder",
    });
    const note = el("div", { class: "small" });
    const use = async (picked: { path: string; file: File }[]) => {
      const size = [...data]
        .filter(([other]) => other !== external)
        .flatMap(([, d]) => d.files)
        .concat(picked)
        .reduce((n, f) => n + f.file.size, 0);
      if (size > MAX_SCRIPT_DATA_BYTES) {
        clear(note).append(
          errorMessage(
            `That's ${Math.ceil(size / 1e6)} MB, more than the ` +
              `${MAX_SCRIPT_DATA_BYTES / 1e6} MB that can be uploaded here.`,
          ),
        );
        return;
      }
      data.set(external, {
        path: dest.value.trim() || `data/${name}`,
        files: picked,
      });
      clear(note).append(loading("Reading"));
      try {
        await reread();
      } catch (e) {
        data.delete(external);
        clear(note).append(
          errorMessage(e instanceof Error ? e.message : String(e)),
        );
      }
    };
    pickFiles.addEventListener("click", () => files.click());
    pickFolder.addEventListener("click", () => folder.click());
    files.addEventListener("change", () => {
      const list = [...(files.files ?? [])];
      // One file is the data itself when it's the one the script names, or
      // else one in that folder
      const single = list.length === 1 && list[0].name === name;
      if (list.length) {
        void use(list.map((file) => ({ path: single ? "" : file.name, file })));
      }
    });
    folder.addEventListener("change", () => {
      const list = [...(folder.files ?? [])];
      if (list.length) {
        void use(
          list.map((file) => ({
            path: file.webkitRelativePath.split("/").slice(1).join("/"),
            file,
          })),
        );
      }
    });
    dest.addEventListener("change", () => {
      if (chosen) {
        void use(chosen.files);
      }
    });
    const n = chosen?.files.length ?? 0;
    const status = !chosen
      ? `Reads ${external}, which is outside the project, so it will only ` +
        "run on the computer it came from. Upload it to read it from the " +
        "project instead:"
      : detected.rewritten?.includes(external)
      ? `Reads ${external}, outside the project. ${n} ` +
        `${n === 1 ? "file" : "files"} will be uploaded to ${chosen.path}, ` +
        "and the script will read them from there."
      : `${n} ${n === 1 ? "file" : "files"} will be uploaded to ` +
        `${chosen.path}, but Calkit couldn't find where the script names ` +
        `${external}; change it to read ${chosen.path}.`;
    return el("div", { class: "stack", style: { marginTop: "4px" } }, [
      el("div", {
        class: "small",
        style: {
          color:
            chosen && detected.rewritten?.includes(external)
              ? ""
              : "var(--ck-warning)",
        },
        text: status,
      }),
      dest,
      el("div", { class: "actions" }, [pickFiles, pickFolder]),
      files,
      folder,
      note,
    ]);
  };
  const renderReview = (detected: StageFromScriptOrNotebookResponse) => {
    review.append(
      el("div", { class: "small" }, [
        document.createTextNode("Stage "),
        el("span", { class: "name", text: detected.stage_name }),
        el("span", {
          class: "dim",
          text:
            ` runs ${request?.scriptPath} in ${detected.environment}` +
            (detected.environment_is_new
              ? `, a new environment${
                  detected.dependencies.length
                    ? ` with ${detected.dependencies.join(", ")}`
                    : ""
                }`
              : ""),
        }),
      ]),
    );
    if (detected.inputs.length) {
      review.append(
        el("div", { class: "small" }, [
          el("span", { class: "dim", text: "Reads " }),
          document.createTextNode(detected.inputs.join(", ")),
        ]),
      );
    }
    if (detected.missing_inputs.length) {
      review.append(
        el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text:
            `Not in the project yet: ${detected.missing_inputs.join(", ")}. ` +
            "Add it, or record where it came from, before running.",
        }),
      );
    }
    for (const external of new Set([
      ...data.keys(),
      ...(detected.external_inputs ?? []),
    ])) {
      review.append(renderExternal(external, detected));
    }
    // Which output this is, when the script writes several or names it
    // differently from the paper
    const choices = detected.outputs.map((output) => {
      const radio = el("input", {
        type: "radio",
        attrs: { name: "ck-produces", value: output },
      });
      radio.checked = output === detected.produces;
      return { output, radio };
    });
    const citeNote = el("div", { class: "dim small" });
    const chosen = () => choices.find((c) => c.radio.checked)?.output;
    const updateNote = () => {
      const output = chosen();
      citeNote.textContent =
        output && output !== shows
          ? `The paper will show it from there, with \\ckfigure{${output}}.`
          : "";
    };
    if (choices.length) {
      review.append(
        el("div", { class: "small dim", text: `Which output is ${shows}?` }),
        ...choices.map(({ output, radio }) => {
          radio.addEventListener("change", updateNote);
          return el("label", { class: "small", style: { display: "block" } }, [
            radio,
            document.createTextNode(` ${output}`),
          ]);
        }),
        citeNote,
      );
      updateNote();
    } else {
      review.append(
        el("div", {
          class: "small dim",
          text: "Calkit didn't find anything the script writes.",
        }),
      );
    }
    const save = el("button", {
      class: "action",
      text: "Add to the pipeline",
    });
    save.addEventListener("click", async () => {
      if (!request) {
        return;
      }
      save.disabled = true;
      clear(message).append(loading(data.size ? "Uploading" : "Saving"));
      try {
        const saved = await send({
          type: "project.stageFromScriptOrNotebook",
          owner,
          project,
          ...request,
          shows,
          produces: chosen(),
          data: await dataRequest(true),
          save: true,
        });
        // Brings the \ckfigure into the editor
        if (saved.included_in.length) {
          clear(message).append(loading("Syncing"));
          await syncOverleaf(owner, project, link.path);
        }
        await showDefined(container, link, citation);
        container.append(renderRunIt(saved, link));
      } catch (e) {
        fail(e);
        save.disabled = false;
      }
    });
    // Only a stage that makes what's shown defines its origin
    if (choices.length) {
      review.append(el("div", { class: "actions" }, [save]));
    }
  };
  return el("div", { class: "stack", style: { marginTop: "6px" } }, [
    el("div", { class: "small" }, [
      document.createTextNode(`The ${kind} that makes `),
      el("span", { class: "name", text: shows }),
    ]),
    file,
    picker,
    el("div", { class: "actions" }, [read]),
    message,
    review,
  ]);
}

/**
 * Record that a figure is exported manually from a file someone made, e.g.,
 * a PNG from a Photoshop file, so the pipeline asks for a new export
 * whenever that file changes.
 */
function renderExported(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
  target: string,
): HTMLElement {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const file = el("input", { type: "file" });
  const { element: picker, input: path } = renderPathPicker({
    owner,
    project,
    placeholder: "Or find it in the project",
    accept: (p) => p !== target && canBeCreatedByPerson(p),
  });
  const appName = textInput({
    placeholder: "App it's exported with, e.g., Photoshop (optional)",
  });
  const save = el("button", { class: "action", text: "Add the export step" });
  const message = el("div", { class: "small" });
  const fail = (e: unknown) =>
    clear(message).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  save.addEventListener("click", async () => {
    clear(message);
    const upload = file.files?.[0];
    const typed = path.value.trim();
    if (!upload && !typed) {
      fail("Choose the file it's exported from, or find it in the project.");
      return;
    }
    // Kept out of the paper's folder, which syncs to Overleaf
    const sourcePath = typed || `figures/src/${upload?.name}`;
    if (!canBeCreatedByPerson(sourcePath)) {
      fail(
        `${sourcePath} is exported from something itself; choose the ` +
          "file it's made from.",
      );
      return;
    }
    save.disabled = true;
    message.append(loading(upload ? "Uploading" : "Saving"));
    try {
      // Whether an app exports it as the pipeline runs, so nobody has to
      // remember to, is the hub's to say
      await send({
        type: "project.addExportStage",
        owner,
        project,
        source: sourcePath,
        output: target,
        app: appName.value.trim() || undefined,
        files: [
          {
            path: sourcePath,
            content: upload ? await fileBase64(upload) : undefined,
            created_by_me: true,
          },
        ],
      });
      await showDefined(container, link, citation);
    } catch (e) {
      fail(e);
      save.disabled = false;
    }
  });
  return el("div", { class: "stack", style: { marginTop: "6px" } }, [
    el("div", { class: "small" }, [
      document.createTextNode("The file "),
      el("span", { class: "name", text: target }),
      document.createTextNode(" is exported from"),
    ]),
    file,
    picker,
    appName,
    el("div", { class: "actions" }, [save]),
    message,
  ]);
}

/** Show what's cited again, now that an origin is defined. */
async function showDefined(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
): Promise<void> {
  provenanceCache.clear();
  void checkCitations();
  const fresh = await citationProvenance(link, citation);
  clear(container);
  renderProvenance(container, link, citation, fresh);
}

/** Record that a file was imported, or made by the signed-in user. */
function renderRecordOrigin(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
  target: string,
  how: "imported" | "created",
): HTMLElement {
  const message = el("div", { class: "small" });
  const fields = el("div", { class: "stack" });
  const save = el("button", { class: "action", text: "Save" });
  let read: () => Promise<Omit<
    ToRecord,
    "type" | "owner" | "project" | "path"
  > | null>;
  if (how === "imported") {
    const sources = [
      ["url", "Website", "https://example.org/data/measurements.csv"],
      ["doi", "DOI", "10.5281/zenodo.1234567"],
      ["git", "Git repo", "https://github.com/owner/repo"],
    ] as const;
    let source: (typeof sources)[number][0] = "url";
    const where = textInput({ placeholder: sources[0][2] });
    const rev = textInput({ placeholder: "Commit or tag (optional)" });
    const repoPath = textInput({ placeholder: "Path in the repo (optional)" });
    const gitFields = el(
      "div",
      { class: "stack", style: { display: "none" } },
      [rev, repoPath],
    );
    const date = el("input", { type: "date" });
    const radios = sources.map(([value, text, placeholder]) => {
      const radio = el("input", {
        type: "radio",
        attrs: { name: "ck-import-source", value },
      });
      radio.checked = value === source;
      radio.addEventListener("change", () => {
        source = value;
        where.placeholder = placeholder;
        gitFields.style.display = value === "git" ? "" : "none";
      });
      return el("label", { class: "small", style: { display: "inline" } }, [
        radio,
        document.createTextNode(` ${text}  `),
      ]);
    });
    fields.append(
      el("div", {}, radios),
      where,
      gitFields,
      el("label", { text: "Retrieved (optional)" }),
      date,
    );
    read = async () => {
      const value = where.value.trim();
      if (!value) {
        return null;
      }
      const when = date.value || null;
      return {
        importedFrom:
          source === "url"
            ? { url: value, date: when }
            : source === "doi"
            ? { doi: value, date: when }
            : {
                git_repo_url: value,
                git_ref: rev.value.trim() || null,
                path: repoPath.value.trim() || null,
                date: when,
              },
      };
    };
  } else {
    const ai = textInput({ placeholder: "Ex: Claude Opus 5" });
    const who = el("div", { class: "small" });
    const user = send({ type: "auth.state" }).then((state) => state.user);
    void user.then((u) => {
      who.textContent = `Created by ${u?.full_name || u?.email || "you"}`;
    });
    fields.append(
      who,
      el("label", { text: "Made with generative AI (optional)" }),
      ai,
    );
    read = async () => {
      const u = await user;
      if (!u) {
        throw new Error("Sign in to say you made it.");
      }
      const tool = ai.value.trim();
      return {
        createdBy: [
          {
            email: u.email,
            name: u.full_name ?? null,
            ...(tool ? { with_ai: [tool] } : {}),
          },
        ],
      };
    };
  }
  save.addEventListener("click", async () => {
    clear(message);
    save.disabled = true;
    try {
      const origin = await read();
      if (!origin) {
        throw new Error("Say where it came from.");
      }
      message.append(loading("Saving"));
      await send({
        type: "project.recordOrigin",
        owner: link.project_owner_name,
        project: link.project_name,
        path: target,
        ...origin,
      });
      await showDefined(container, link, citation);
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      save.disabled = false;
    }
  });
  return el("div", { class: "stack", style: { marginTop: "6px" } }, [
    el("div", { class: "small" }, [
      document.createTextNode(how === "imported" ? "Where " : "Who made "),
      el("span", { class: "name", text: target }),
      document.createTextNode(how === "imported" ? " came from" : ""),
    ]),
    fields,
    el("div", { class: "actions" }, [save]),
    message,
  ]);
}

type ToRecord = Extract<Request, { type: "project.recordOrigin" }>;

/** The ways to define where a file came from, each opening its form. */
function renderDefineOrigin(
  link: OverleafLinkPublic,
  citation: Citation,
  target: string,
): HTMLElement {
  const open = (form: (body: HTMLElement) => HTMLElement) =>
    showInPanel((body) => body.append(form(body)));
  const choices: [string, () => void][] = [
    [
      "Script",
      () =>
        open((body) => renderAddScript(body, link, citation, target, "script")),
    ],
    [
      "Notebook",
      () =>
        open((body) =>
          renderAddScript(body, link, citation, target, "notebook"),
        ),
    ],
    [
      "Imported",
      () =>
        open((body) =>
          renderRecordOrigin(body, link, citation, target, "imported"),
        ),
    ],
  ];
  // Something exported, e.g., a PNG, comes from a file a person made
  if (!canBeCreatedByPerson(target)) {
    choices.push([
      "Exported",
      () => open((body) => renderExported(body, link, citation, target)),
    ]);
  }
  if (canBeCreatedByPerson(target)) {
    choices.push([
      "Created",
      () =>
        open((body) =>
          renderRecordOrigin(body, link, citation, target, "created"),
        ),
    ]);
  }
  return el(
    "div",
    {
      class: "actions",
      style: { alignItems: "center", flexWrap: "wrap", marginTop: "4px" },
    },
    [
      el("span", { class: "small dim", text: "Define origin:" }),
      ...choices.map(([text, onClick]) =>
        el("button", { class: "action secondary", text, onClick }),
      ),
    ],
  );
}

/** How to run a stage that's never run, since Overleaf can't. */
function renderRunIt(
  saved: StageFromScriptOrNotebookResponse,
  link: OverleafLinkPublic,
): HTMLElement {
  if (link.local_path) {
    return el("div", { class: "muted-box", style: { marginTop: "6px" } }, [
      el("div", {
        class: "small",
        text:
          `Added stage ${saved.stage_name}. It hasn't run yet. Run it on ` +
          "this computer, and its results come into this paper when it " +
          "finishes:",
      }),
      renderRuns(link, true),
    ]);
  }
  const folder = saved.git_repo_url
    .replace(/\.git$/, "")
    .split("/")
    .pop();
  const commands = [
    "curl -LsSf install.calkit.org | sh",
    `calkit clone ${link.project_owner_name}/${link.project_name}`,
    `cd ${folder}`,
    "calkit run --save --overleaf",
  ].join("\n");
  const copy = el("button", { class: "action secondary", text: "Copy" });
  copy.addEventListener("click", async () => {
    await navigator.clipboard.writeText(commands);
    copy.textContent = "Copied";
  });
  return el("div", { class: "muted-box", style: { marginTop: "6px" } }, [
    el("div", {
      class: "small",
      text:
        `Added stage ${saved.stage_name}. It hasn't run yet. Run it on ` +
        "GitHub Actions, and its results come into this paper when it " +
        "finishes:",
    }),
    renderRuns(link, true),
    el("div", {
      class: "small",
      style: { marginTop: "6px" },
      text: "Or on your computer:",
    }),
    el("pre", {
      class: "name",
      style: { whiteSpace: "pre-wrap", margin: "6px 0" },
      text: commands,
    }),
    el("div", { class: "actions" }, [copy]),
  ]);
}

// The project's pipeline runs, checked often while one is going, so a
// finished run syncs to Overleaf even with the panel closed, and now and
// then otherwise, to see ones started elsewhere
let pipelineRuns: {
  key: string;
  runs: PipelineRuns;
  // What the last finished run did here
  notice?: string;
} | null = null;
let runsTimer: ReturnType<typeof setTimeout> | undefined;
// The check going now, which others wait on rather than repeat
let runsRequest: { key: string; promise: Promise<void> } | null = null;
// Checks that failed in a row, which space the next ones out
let runsFailures = 0;
// A start from a run button, kept across their redraws
let starting: { key: string; busy: boolean; error?: string } | null = null;
// Whether syncing from this computer runs what's out of date first, as last
// chosen, and whether the latest run synced after
const RUN_BEFORE_SYNC_KEY = "runBeforeSync";
let runBeforeSync = true;
let lastRunSynced = true;
void chrome.storage.local.get(RUN_BEFORE_SYNC_KEY).then((stored) => {
  runBeforeSync = stored[RUN_BEFORE_SYNC_KEY] ?? true;
});
// Where the open panel shows them, redrawn as they change
const runsBoxes = new Set<{
  box: HTMLElement;
  link: OverleafLinkPublic;
  offer: boolean;
}>();

function linkKey(link: OverleafLinkPublic): string {
  return `${link.project_owner_name}/${link.project_name}`;
}

/** Whether the user can change the project, e.g., run or sync it. */
function canWrite(link: OverleafLinkPublic): boolean {
  return ["write", "admin", "owner"].includes(link.current_user_access ?? "");
}

/** The run going now, if there is one. */
function activeRun(): PipelineRun | null {
  const latest = pipelineRuns?.runs.runs[0];
  return latest && ["queued", "running"].includes(latest.status)
    ? latest
    : null;
}

/** Show what's going on on the launcher, while the panel is closed. */
function remountLauncher(): void {
  if (!panel && currentProjectId) {
    const id = currentProjectId;
    mountLauncher(() => openPanel(id), launcherTone());
  }
}

/**
 * Check the project's runs, and keep checking: often while one is going,
 * now and then otherwise, less often after failures, and not while the tab
 * is hidden. A check already going is waited on rather than repeated.
 */
function refreshRuns(link: OverleafLinkPublic): Promise<void> {
  const key = linkKey(link);
  const schedule = () => {
    clearTimeout(runsTimer);
    const delay = runsFailures
      ? Math.min(15_000 * 2 ** runsFailures, 300_000)
      : activeRun()?.location === "local"
      ? 2_000
      : activeRun()
      ? 15_000
      : 60_000;
    runsTimer = setTimeout(() => {
      if (document.hidden) {
        schedule();
      } else {
        void refreshRuns(link);
      }
    }, delay);
  };
  const check = async () => {
    const known = pipelineRuns?.key === key ? pipelineRuns : null;
    const wasRunning = Boolean(known && activeRun());
    let runs: PipelineRuns;
    try {
      runs = await send({
        type: "project.pipelineRuns",
        owner: link.project_owner_name,
        project: link.project_name,
      });
      runsFailures = 0;
    } catch {
      runsFailures++;
      schedule();
      return;
    }
    if (currentLink && linkKey(currentLink) !== key) {
      return;
    }
    pipelineRuns = { key, runs, notice: known?.notice };
    if (!activeRun() && wasRunning) {
      if (railOpen) {
        void refreshRailPipeline(link);
      }
      if (runs.runs[0]?.status === "succeeded") {
        await bringInRun(link);
      } else {
        pipelineRuns.notice = undefined;
      }
    }
    schedule();
    drawRuns();
    drawRail();
    remountLauncher();
  };
  if (runsRequest?.key === key) {
    return runsRequest.promise;
  }
  const promise = check().finally(() => {
    if (runsRequest?.promise === promise) {
      runsRequest = null;
    }
  });
  runsRequest = { key, promise };
  return promise;
}

/** Sync the paper with its project, showing that it's going meanwhile. */
async function syncOverleaf(
  owner: string,
  project: string,
  path: string,
): Promise<OverleafSyncResponse> {
  syncing = true;
  drawRail();
  drawStatusParts();
  remountLauncher();
  try {
    return await send({ type: "overleaf.sync", owner, project, path });
  } finally {
    syncing = false;
    drawRail();
    drawStatusParts();
    remountLauncher();
  }
}

/** Look again at what's synced and shown, now that a sync changed it. */
function afterSync(): void {
  provenanceCache.clear();
  checkingAfterSync = true;
  drawStatusParts();
  // What was just built and synced, rather than what was
  if (localPdf) {
    showLocalPdf(localPdf.link, localPdf.path);
  }
  // A run or sync changes which stages are out of date
  if (currentLink?.local_path) {
    void refreshRailPipeline(currentLink);
  }
  if (!currentProjectId) {
    return;
  }
  if (panel) {
    void load(currentProjectId);
  } else {
    void checkSyncStatus(currentProjectId);
  }
}

// Why the last sync from a Sync now button failed, kept across redraws
let syncError: string | undefined;

/** A Sync now button, for where a sync is all that's needed. */
function syncNow(
  link: OverleafLinkPublic,
  path: string,
  secondary = false,
): { button: HTMLElement; message: HTMLElement } {
  const message = el("div", { class: "small" }, [
    syncError ? errorMessage(syncError) : null,
  ]);
  const button = el("button", {
    class: secondary ? "action secondary" : "action",
    text: "Sync now",
    disabled: !canWrite(link) || syncing,
    title: canWrite(link)
      ? "Push project files to Overleaf and pull Overleaf edits back"
      : "You need write access to this project to sync",
  });
  button.addEventListener("click", async () => {
    button.disabled = true;
    syncError = undefined;
    clear(message).append(loading("Syncing"));
    try {
      await syncOverleaf(link.project_owner_name, link.project_name, path);
      clear(message).append(el("div", { class: "dim", text: "Synced." }));
      afterSync();
    } catch (e) {
      syncError = e instanceof Error ? e.message : String(e);
      button.disabled = false;
      clear(message).append(errorMessage(syncError));
    }
  });
  return { button, message };
}

/**
 * Start the pipeline on this computer, saving and syncing after if chosen,
 * or else on GitHub Actions, which syncs here when it's done.
 */
async function startRun(link: OverleafLinkPublic): Promise<void> {
  const key = linkKey(link);
  starting = { key, busy: true };
  // A run started here syncs after; only one from before may not have
  lastRunSynced = true;
  drawRuns();
  try {
    const run = await send({
      type: "project.startPipelineRun",
      owner: link.project_owner_name,
      project: link.project_name,
      sync: lastRunSynced,
    });
    starting = null;
    // Listed as soon as it's recorded, before GitHub lists it
    if (pipelineRuns?.key === key) {
      pipelineRuns.runs.runs.unshift(run);
      pipelineRuns.notice = undefined;
    }
  } catch (e) {
    starting = {
      key,
      busy: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
  drawRuns();
  drawRail();
  remountLauncher();
  if (!starting) {
    // One that was already going may not have it yet
    await runsRequest?.promise;
    await refreshRuns(link);
  }
}

/** Bring what a finished run made into this paper. */
async function bringInRun(link: OverleafLinkPublic): Promise<void> {
  if (!pipelineRuns) {
    return;
  }
  // 'calkit run --save --overleaf' synced already, unless it was only run
  if (pipelineRuns.runs.runs[0]?.location === "local") {
    pipelineRuns.notice = lastRunSynced
      ? "The pipeline ran on this computer, and its results were saved " +
        "and synced here."
      : "The pipeline ran on this computer. Sync to bring its results here.";
  } else if (canWrite(link)) {
    try {
      await syncOverleaf(link.project_owner_name, link.project_name, link.path);
      pipelineRuns.notice =
        "The pipeline finished on GitHub Actions, and its results were " +
        "synced here.";
    } catch (e) {
      pipelineRuns.notice =
        "The pipeline finished on GitHub Actions, but syncing failed: " +
        (e instanceof Error ? e.message : String(e));
    }
  }
  afterSync();
}

/**
 * The pipeline's latest run, and a button to start one when ``offer``
 * says there's something to run.
 */
function renderRuns(link: OverleafLinkPublic, offer: boolean): HTMLElement {
  const box = el("div", { style: { marginTop: "6px" } });
  runsBoxes.add({ box, link, offer });
  if (pipelineRuns?.key === linkKey(link)) {
    drawRuns();
  } else if (!runsFailures) {
    // Failed checks are retried on a timer instead
    void refreshRuns(link);
  }
  return box;
}

function drawRuns(): void {
  drawStatusParts();
  drawPanelActions();
  for (const entry of runsBoxes) {
    const { box, link, offer } = entry;
    if (!box.isConnected && box.dataset.drawn) {
      runsBoxes.delete(entry);
      continue;
    }
    box.dataset.drawn = "1";
    clear(box);
    if (pipelineRuns?.key !== linkKey(link)) {
      continue;
    }
    const { runs, notice } = pipelineRuns;
    const run = activeRun();
    const latest = runs.runs[0];
    const view = (r: PipelineRun, text: string) =>
      r.url
        ? el("a", { text, href: r.url, attrs: { target: "_blank" } })
        : null;
    if (run) {
      const since = run.started
        ? ` since ${new Date(run.started).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit",
          })}`
        : "";
      box.append(
        el("div", { class: "row" }, [
          el("span", { class: "spinner" }),
          el("div", {
            class: "grow small",
            text:
              run.location === "local"
                ? getRunActivity(run)
                : run.status === "running"
                ? `Running ${getRunPlace(run)}${since}`
                : `Waiting to run ${getRunPlace(run)}`,
          }),
          run.location === "local"
            ? el("button", {
                class: "action secondary",
                text: "Show log",
                onClick: () => openRunLog(link, run),
              })
            : view(run, "View"),
        ]),
      );
      // The last of what it's printed, with the rest a click away
      if (run.location === "local" && run.output) {
        box.append(
          el("pre", {
            class: "log",
            text: run.output.split("\n").slice(-3).join("\n"),
          }),
        );
      }
      continue;
    }
    if (notice) {
      box.append(el("div", { class: "dim small", text: notice }));
    } else if (latest?.status === "failed") {
      box.append(
        el("div", { class: "row" }, [
          el("div", {
            class: "grow small",
            text:
              `The last run ${getRunPlace(latest)} failed` +
              (latest.error ? `: ${latest.error}` : "."),
            title: latest.output ?? "",
          }),
          latest.location === "local"
            ? el("button", {
                class: "action secondary",
                text: "Show log",
                onClick: () => openRunLog(link, latest),
              })
            : view(latest, "See why"),
        ]),
      );
    }
    // Something the document shows being out of date is reason to run
    // too, even when Overleaf has what the project has
    const staleShown = editorProblems?.found.some((problems) =>
      problems.some((p) => p.kind === "stale"),
    );
    // On this computer, running is part of syncing, below
    if (
      link.local_path ||
      (!offer && !staleShown && latest?.status !== "failed")
    ) {
      continue;
    }
    const mine = starting?.key === linkKey(link) ? starting : null;
    const start = el("button", {
      class: "action",
      text: "Run and sync",
      disabled: !canWrite(link) || !runs.can_start || Boolean(mine?.busy),
      title: !canWrite(link)
        ? "You need write access to this project to run it"
        : runs.cannot_start_reason ??
          "Run the pipeline on GitHub Actions, then sync what it makes here",
      onClick: () => void startRun(link),
    });
    box.append(
      el("div", { class: "actions" }, [start]),
      mine?.busy
        ? loading("Starting")
        : mine?.error
        ? errorMessage(mine.error)
        : el("div"),
    );
  }
}

/** What a run on this computer is doing now, as a line would say it. */
function getRunActivity(run: PipelineRun): string {
  const progress = run.progress;
  if (run.status === "queued") {
    return "Waiting to run on this computer";
  }
  const of = progress?.n_stages ? ` of ${progress.n_stages}` : "";
  switch (progress?.phase) {
    case "syncing":
      return "Syncing with Overleaf";
    case "running":
      return progress.stage
        ? `Running stage ${progress.n_done + 1}${of}: ${progress.stage}`
        : `Checking stages (${progress.n_done}${of} done)`;
    case "finishing":
      return "Finishing up";
    case "saving":
      return "Saving the project";
    default:
      return "Getting ready to run on this computer";
  }
}

/**
 * Show the whole log of a run on this computer, kept up to date while it
 * runs.
 */
function openRunLog(link: OverleafLinkPublic, run: PipelineRun): void {
  const started = run.started ?? run.created;
  const overlay = mountOverlay({
    id: "calkit-run-log",
    title: `Run on this computer, ${new Date(started).toLocaleString([], {
      dateStyle: "medium",
      timeStyle: "short",
    })}`,
  });
  const log = el("pre", { class: "log", text: "Loading…" });
  overlay.viewport.append(log);
  const refresh = async () => {
    if (!overlay.host.isConnected) {
      return;
    }
    try {
      const { log: text } = await send({
        type: "project.pipelineRunLog",
        owner: link.project_owner_name,
        project: link.project_name,
        runId: run.id,
      });
      // Kept at the end as it grows, unless scrolled back to read
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
      log.textContent = text || "Nothing printed yet.";
      if (atEnd) {
        log.scrollTop = log.scrollHeight;
      }
    } catch (e) {
      log.textContent = e instanceof Error ? e.message : String(e);
    }
    const latest = pipelineRuns?.runs.runs.find((r) => r.id === run.id);
    if (latest && ["queued", "running"].includes(latest.status)) {
      setTimeout(() => void refresh(), 2_000);
    }
  };
  void refresh();
}

// The parts of the open panel's status that a run or sync going on makes
// out of date, set aside meanwhile rather than shown as current
const statusParts = new Set<{
  link: OverleafLinkPublic;
  hide: HTMLElement[];
  busy: HTMLElement;
}>();
// Whether what's shown is from before a run or sync that's just ended, until
// it's been checked again
let checkingAfterSync = false;

/** What's going on that makes the status shown out of date, if anything. */
function getStatusBusyText(link: OverleafLinkPublic): string | null {
  if (syncing) {
    return "Syncing with Overleaf";
  }
  const run = pipelineRuns?.key === linkKey(link) ? activeRun() : null;
  if (run) {
    return run.progress?.phase === "syncing"
      ? "Syncing with Overleaf"
      : "What to sync is checked again once the run is done.";
  }
  return checkingAfterSync ? "Checking what's synced now" : null;
}

function drawStatusParts(): void {
  for (const entry of statusParts) {
    if (!entry.busy.isConnected && entry.busy.dataset.drawn) {
      statusParts.delete(entry);
      continue;
    }
    entry.busy.dataset.drawn = "1";
    const text = getStatusBusyText(entry.link);
    for (const part of entry.hide) {
      part.style.display = text ? "none" : "";
    }
    clear(entry.busy);
    if (text) {
      entry.busy.append(
        text.endsWith(".")
          ? el("div", {
              class: "dim small",
              style: { marginTop: "8px" },
              text,
            })
          : el("div", { style: { marginTop: "8px" } }, [loading(text)]),
      );
    }
  }
}

/** A file's contents, base64-encoded, as the hub takes an upload. */
function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () =>
      resolve(String(reader.result).replace(/^data:[^,]*,/, ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

/**
 * What produced a figure, table, or value the document shows, and whether
 * it's current.
 *
 * Overleaf can't run the pipeline, so the actions are ways into the
 * project: the script to edit, and the page in the hub with the rest.
 */
function renderProvenance(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
  provenance: Provenance,
  named = true,
): void {
  const base = projectUrl(
    hubWebUrl,
    link.project_owner_name,
    link.project_name,
  );
  const fileUrl = (path: string) =>
    `${base}/files?path=${encodeURIComponent(path)}`;
  // Where each input came from, a level at a time, so the chain can be
  // followed back to an import, a person, or a gap
  const trace = (paths: string[], seen: Set<string>): HTMLElement => {
    const list = el("div");
    for (const input of paths) {
      const toggle = el("button", {
        class: "twisty",
        type: "button",
        text: "\u25b8",
        title: `Where ${input} came from`,
      });
      const detail = el("div", { class: "trace-detail small" });
      detail.hidden = true;
      let loaded = false;
      toggle.addEventListener("click", async () => {
        detail.hidden = !detail.hidden;
        toggle.textContent = detail.hidden ? "\u25b8" : "\u25be";
        if (loaded || detail.hidden) {
          return;
        }
        loaded = true;
        clear(detail).append(loading());
        try {
          const p = await provenanceFor(link, input);
          const original = p.copied_from ?? p.path;
          const lines: HTMLElement[] = [];
          if (p.copied_from) {
            lines.push(
              el("div", { class: "dim" }, [
                document.createTextNode("Copied from "),
                el("a", { text: p.copied_from, href: fileUrl(p.copied_from) }),
              ]),
            );
          }
          if (p.stage) {
            lines.push(
              el("div", {}, [
                document.createTextNode("Stage "),
                el("a", {
                  text: p.stage,
                  href: `${base}/pipeline?stage=${encodeURIComponent(p.stage)}`,
                }),
                p.stage_kind
                  ? el("span", {
                      class: "dim",
                      text: ` \u00b7 ${p.stage_kind}`,
                    })
                  : null,
                p.stale_reason
                  ? el("span", { class: "badge warn", text: "stale" })
                  : null,
              ]),
            );
            if (p.stage_kind === "manual-step" && p.message) {
              lines.push(
                el("div", { class: "dim", text: `Manual step: ${p.message}` }),
              );
            } else if (p.source) {
              lines.push(
                el("div", { class: "dim" }, [
                  document.createTextNode(
                    p.stage_app
                      ? `Exported with ${p.stage_app} from `
                      : "Runs ",
                  ),
                  el("a", { text: p.source, href: fileUrl(p.source) }),
                ]),
              );
            }
          } else if (p.origin) {
            lines.push(
              p.origin_url
                ? el("a", { text: p.origin, href: p.origin_url })
                : el("div", { text: p.origin }),
            );
          } else if (p.gaps?.some((gap) => gap.path === original)) {
            lines.push(
              el("div", {
                text: "Origin not defined",
                style: { color: "var(--ck-danger)", fontWeight: "600" },
              }),
            );
          } else if (!p.exists) {
            lines.push(el("div", { class: "dim", text: "Not in the project" }));
          } else {
            lines.push(el("div", { class: "dim", text: "Source file" }));
          }
          const next = new Set([...seen, input, original]);
          const upstream = p.inputs.filter((i) => !next.has(i));
          if (upstream.length) {
            lines.push(
              el("div", { class: "dim", text: "Reads" }),
              trace(upstream, next),
            );
          }
          clear(detail).append(...lines);
        } catch (e) {
          loaded = false;
          clear(detail).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
        }
      });
      list.append(
        el("div", { class: "small" }, [
          toggle,
          el("a", { text: input, href: fileUrl(input) }),
        ]),
        detail,
      );
    }
    return list;
  };
  // A file is named as the project has it, not as written. In the
  // sidebar's list, its row already names it.
  const path = citation.kind === "value" ? citation.path : provenance.path;
  const label = citation.key ? `${path}: ${citation.key}` : path;
  if (named) {
    container.append(el("div", { class: "name", text: label }));
  }
  const problems = citationProblems(citation, provenance);
  for (const problem of problems) {
    container.append(problemLine(problem));
  }
  // Defined in one place, since several components can be made from it
  if (
    problems.some((p) => p.kind === "origin") &&
    link.current_user_access !== "read"
  ) {
    container.append(
      el("div", { class: "small" }, [
        el("a", {
          text: named ? "Define it in the Calkit sidebar" : "Define it above",
          onClick: (event) => {
            event.preventDefault();
            if (!railOpen) {
              setRail(true);
            }
            // In the sidebar's shadow root
            railPane?.body
              .querySelector("#calkit-origin-needed")
              ?.scrollIntoView({ block: "start", behavior: "smooth" });
          },
        }),
      ]),
    );
  }
  if (provenance.copied_from) {
    container.append(
      el("div", { class: "dim small" }, [
        document.createTextNode("Copied from "),
        el("a", {
          text: provenance.copied_from,
          href: fileUrl(provenance.copied_from),
          attrs: { target: "_blank" },
        }),
        provenance.copy_stage
          ? document.createTextNode(` by ${provenance.copy_stage}`)
          : null,
      ]),
    );
  }
  if (
    citation.kind === "value" &&
    !provenance.value_error &&
    provenance.value !== undefined
  ) {
    container.append(
      el("div", {
        style: { fontWeight: "600", margin: "4px 0" },
        title: valueText(provenance.value),
        text: getShownValue(provenance.value, citation.options),
      }),
    );
  }
  if (!provenance.stage && provenance.origin) {
    container.append(
      el("div", { class: "small" }, [
        provenance.origin_url
          ? el("a", {
              text: provenance.origin,
              href: provenance.origin_url,
              attrs: { target: "_blank" },
            })
          : document.createTextNode(provenance.origin),
        provenance.origin_path
          ? el("span", {
              class: "dim",
              text: ` (recorded for ${provenance.origin_path})`,
            })
          : null,
      ]),
    );
  } else if (provenance.stage) {
    container.append(
      el("div", { class: "row" }, [
        el("div", { class: "grow small" }, [
          document.createTextNode("Stage "),
          el("a", {
            text: provenance.stage,
            title: provenance.stage_kind ?? undefined,
            href: `${base}/pipeline?stage=${encodeURIComponent(
              provenance.stage,
            )}`,
            attrs: { target: "_blank" },
          }),
        ]),
        !provenance.stale_reason &&
        provenance.stage_status?.status === "up-to-date"
          ? el("span", { class: "badge ok", text: "current" })
          : null,
      ]),
    );
    if (provenance.stage_kind === "manual-step" && provenance.message) {
      container.append(
        el("div", {
          class: "small",
          text: `Manual step: ${provenance.message}`,
        }),
      );
    } else if (provenance.source) {
      const source = el("a", {
        text: provenance.source,
        href: fileUrl(provenance.source),
        attrs: { target: "_blank" },
      });
      container.append(
        el(
          "div",
          { class: "small" },
          provenance.stage_app
            ? [
                document.createTextNode(
                  `Exported with ${provenance.stage_app} from `,
                ),
                source,
              ]
            : [
                document.createTextNode("Made by "),
                source,
                document.createTextNode(" "),
                renderOpenLocally(
                  `${link.project_owner_name}/${link.project_name}`,
                  provenance.source,
                  true,
                ),
              ],
        ),
      );
    }
    if (provenance.inputs.length) {
      container.append(
        el("div", {
          class: "dim small",
          text: "Reads",
          style: { marginTop: "4px" },
        }),
        trace(
          provenance.inputs,
          new Set([path, provenance.copied_from ?? path]),
        ),
      );
    }
  }
  container.append(
    el("div", { class: "small", style: { marginTop: "6px" } }, [
      el("a", {
        text: "Open in Calkit",
        href:
          citation.kind === "value"
            ? `${base}/results?path=${encodeURIComponent(path)}` +
              `&key=${encodeURIComponent(citation.key ?? "")}`
            : citation.kind === "figure"
            ? `${base}/figures?path=${encodeURIComponent(
                provenance.copied_from ?? path,
              )}`
            : citation.kind === "table"
            ? `${base}/tables?path=${encodeURIComponent(path)}`
            : fileUrl(path),
        attrs: { target: "_blank" },
      }),
    ]),
  );
}

// Whether Calkit on this computer answers, asked once per page, since the
// browser starts it to find out
let localStatus: Promise<LocalStatus> | null = null;

/**
 * A button that opens the project in the editor on this computer, at a
 * file if given, e.g., the notebook that makes a figure, through Calkit
 * here rather than a hub, or installs the editor first if it isn't there.
 */
function renderOpenLocally(
  project: string,
  path?: string,
  inline = false,
  // Shown as a link, e.g., the checkout's path, rather than a button
  shown?: string,
): HTMLElement {
  localStatus ??= send({ type: "local.status" }).catch(() => ({
    permitted: false,
  }));
  const open = el("button", {
    class: shown ? "link" : "action secondary",
    text: shown ?? "Open in editor",
    title: path ? `Open ${path} on this computer` : "Open it on this computer",
  });
  const message = el("div", { class: "small" });
  const label = (status: LocalStatus) => {
    const editor = getEditorLabel(status.editor);
    const text =
      status.editorInstalled === false
        ? `Install ${editor}`
        : `Open in ${editor}`;
    if (shown) {
      open.title = text;
    } else {
      open.textContent = text;
    }
  };
  void localStatus.then(label);
  open.addEventListener("click", async () => {
    const status = await (localStatus as Promise<LocalStatus>);
    if (!status.version) {
      // Asked again next time, e.g., once it's been connected
      localStatus = null;
      clear(message).append(
        el("span", {
          text: status.permitted
            ? `${status.error ?? "Calkit on this computer didn't answer"}. `
            : "Connect the extension to Calkit on this computer first. ",
        }),
        el("button", {
          class: "action secondary",
          text: "Connect",
          onClick: () => void send({ type: "local.openOptions" }),
        }),
      );
      return;
    }
    open.disabled = true;
    try {
      if (status.editorInstalled === false) {
        clear(message).append(
          loading(`Installing ${getEditorLabel(status.editor)}`),
        );
        await send({ type: "local.installEditor", project });
        localStatus = send({ type: "local.status" });
        label(await localStatus);
      }
      clear(message).append(loading("Opening"));
      await send({ type: "local.openProject", project, path });
      clear(message);
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    } finally {
      open.disabled = false;
    }
  });
  if (inline) {
    message.classList.add("line-message");
    return el("div", { style: { display: "contents" } }, [open, message]);
  }
  return el("div", { style: { marginTop: "4px" } }, [open, message]);
}

/**
 * What's on this computer that Overleaf won't see until it's saved and
 * synced, e.g., a figure remade by running a notebook, or a way to connect
 * if the extension isn't connected to Calkit here. With ``localPath``, the
 * checkout the panel already works with, only what the panel doesn't show
 * otherwise, i.e., what isn't saved or pushed.
 */
function renderLocalChanges(
  project: string,
  reload: () => void,
  localPath?: string | null,
): HTMLElement {
  const container = el("div");
  localStatus ??= send({ type: "local.status" }).catch(() => ({
    permitted: false,
  }));
  void (async () => {
    const status = await (localStatus as Promise<LocalStatus>);
    if (!status.version) {
      // Asked again next time, e.g., once it's been connected
      localStatus = null;
      container.append(
        el("div", { class: "row", style: { marginTop: "8px" } }, [
          el("div", {
            class: "dim small grow",
            text: status.permitted
              ? `${status.error ?? "Calkit on this computer didn't answer"}.`
              : "Connect this computer to see what's on it that Overleaf " +
                "doesn't have yet.",
          }),
          el("button", {
            class: "action secondary",
            text: "Connect",
            onClick: () => void send({ type: "local.openOptions" }),
          }),
        ]),
      );
      return;
    }
    // Not here yet, so offered, since working on it here is the point
    const local = await send({ type: "local.checkout", project }).catch(
      () => null,
    );
    if (local && !local.path) {
      container.append(renderClone(project, reload));
      return;
    }
    // Which of several, e.g., worktrees, answers for it
    if (local && local.paths.length > 1) {
      const choice = el(
        "select",
        { class: "small", title: "The checkout this panel uses" },
        local.paths.map((p) => el("option", { text: p, value: p })),
      );
      choice.value = local.path ?? "";
      choice.addEventListener("change", async () => {
        await send({
          type: "local.chooseCheckout",
          project,
          path: choice.value,
        });
        reload();
      });
      container.append(
        el("div", { class: "row small", style: { marginTop: "8px" } }, [
          el("span", { class: "dim", text: "Using" }),
          choice,
        ]),
      );
    }
    let checkouts: CheckoutStatus[];
    try {
      ({ checkouts } = await send({ type: "local.projectStatus", project }));
    } catch (e) {
      container.append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    let pendingCount = 0;
    const plural = (n: number, word: string) =>
      `${n} ${word}${n === 1 ? "" : "s"}`;
    if (localPath) {
      checkouts = checkouts.filter((c) => c.path === localPath);
    }
    for (const checkout of checkouts) {
      const lines: HTMLElement[] = [];
      if (checkout.n_unsaved_files) {
        lines.push(
          el("div", {
            class: "small",
            text: `${plural(checkout.n_unsaved_files, "file")} not saved`,
            title: checkout.unsaved_files.join("\n"),
          }),
        );
      }
      if (checkout.commits_ahead) {
        lines.push(
          el("div", {
            class: "small",
            text:
              `${plural(checkout.commits_ahead, "saved change")} not ` +
              "pushed to GitHub",
          }),
        );
      }
      // The panel lists what a sync would send for its own checkout
      for (const folder of localPath ? [] : checkout.overleaf) {
        const n =
          (folder.n_files_to_push ?? 0) + (folder.n_files_to_delete ?? 0);
        if (folder.syncing) {
          lines.push(el("div", { class: "small", text: "Syncing now" }));
        } else if (folder.never_synced) {
          lines.push(
            el("div", {
              class: "small",
              text: `${folder.path} hasn't been synced from here yet`,
            }),
          );
        } else if (folder.error) {
          lines.push(errorMessage(folder.error));
        } else if (n) {
          lines.push(
            el("div", {
              class: "small",
              text: `${plural(n, "file")} in ${folder.path} not synced here`,
              title: (folder.files_to_push ?? []).join("\n"),
            }),
          );
        }
      }
      if (!lines.length) {
        continue;
      }
      pendingCount++;
      if (localPath) {
        container.append(el("div", { style: { marginTop: "6px" } }, lines));
        continue;
      }
      container.append(
        el("div", { class: "muted-box", style: { marginTop: "8px" } }, [
          el("div", { class: "row" }, [
            el("div", { class: "grow" }, [
              el("div", { class: "small", text: "On this computer" }),
              el("div", { class: "dim small", text: checkout.path }),
            ]),
            el("span", { class: "badge warn", text: "not synced" }),
          ]),
          ...lines,
          el("div", {
            class: "dim small",
            style: { marginTop: "4px" },
            text: "Run and sync there to bring them here.",
          }),
        ]),
      );
    }
    // Only checkouts with something to bring here are listed, since
    // someone may have several, e.g., Git worktrees
    if (checkouts.length && !pendingCount && !localPath) {
      container.append(
        el("div", {
          class: "dim small",
          style: { marginTop: "6px" },
          text: "Everything on this computer is saved and synced.",
        }),
      );
    }
  })();
  return container;
}

/**
 * Clone a project that isn't on this computer, so this panel works with
 * it here from then on.
 */
function renderClone(project: string, reload: () => void): HTMLElement {
  const name = project.split("/")[1];
  const location = el("input", {
    class: "small",
    type: "text",
    value: `~/calkit/${name}`,
    title: "Where to put it",
  });
  const message = el("div", { class: "small" });
  const clone = el("button", {
    class: "action",
    text: "Clone to this computer",
  });
  clone.addEventListener("click", async () => {
    clone.disabled = true;
    clear(message).append(loading("Cloning"));
    try {
      await send({
        type: "local.clone",
        project,
        location: location.value.trim() || undefined,
      });
      reload();
    } catch (e) {
      clone.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  return el("div", { class: "muted-box", style: { marginTop: "8px" } }, [
    el("div", {
      class: "small",
      text:
        "This project isn't on this computer. Clone it to run, save, and " +
        "sync from here:",
    }),
    el("div", { class: "row", style: { marginTop: "6px" } }, [location, clone]),
    message,
  ]);
}

/** One problem, colored by how bad it is. */
function problemLine(problem: CitationProblem): HTMLElement {
  return el("div", {
    class: "small",
    style: {
      color:
        problem.severity === "error" ? "var(--ck-danger)" : "var(--ck-warning)",
      fontWeight: "600",
    },
    text: problem.message,
  });
}

type Without<T> = T extends unknown ? Omit<T, "calkit"> : never;

// The editor's count of scans, which go up with each edit, so the first
// one, when it opens, isn't taken for an edit
let lastEditorVersion: number | null = null;

// What the editor last said the open document shows, and what's wrong with
// each, by its index there
let editorCitations: { version: number; items: EditorCitation[] } | null = null;
let editorProblems: { version: number; found: CitationProblem[][] } | null =
  null;

function toEditor(message: Without<ToEditor>): void {
  window.postMessage({ calkit: "lint", ...message }, window.location.origin);
}

/** Find what's wrong with what the open document shows, and mark it. */
async function checkCitations(): Promise<void> {
  const link = currentLink;
  const snapshot = editorCitations;
  if (!link || !snapshot) {
    return;
  }
  const found: CitationProblem[][] = [];
  // A few at a time, since each has the hub read the project
  let next = 0;
  const work = async () => {
    while (next < snapshot.items.length) {
      const i = next++;
      const { citation } = snapshot.items[i];
      try {
        found[i] = citationProblems(
          citation,
          await citationProvenance(link, citation),
        );
      } catch {
        found[i] = [];
      }
    }
  };
  await Promise.all([work(), work(), work(), work()]);
  if (editorCitations !== snapshot || currentLink !== link) {
    return;
  }
  editorProblems = { version: snapshot.version, found };
  drawRuns();
  drawRail();
  markRailTab();
  toEditor({
    type: "problems",
    version: snapshot.version,
    items: found.flatMap((problems, index) =>
      problems.length
        ? [
            {
              index,
              severity: problems.some((p) => p.severity === "error")
                ? "error"
                : "warning",
            },
          ]
        : [],
    ),
  });
  void drawPdfBoxes();
}

const TOOLTIP_STYLES = `
.tip {
  color: var(--ck-fg);
  background: var(--ck-bg);
  padding: 8px 10px;
  max-width: 360px;
  max-height: 50vh;
  overflow-y: auto;
}
`;

/** Fill a tooltip the editor opened over something the document shows. */
async function fillTooltip(
  id: string,
  version: number,
  index: number,
): Promise<void> {
  const link = currentLink;
  const item =
    editorCitations?.version === version
      ? editorCitations.items[index]
      : undefined;
  if (!link || !item) {
    return;
  }
  // Made as the tooltip opens, so it may not be on the page quite yet
  let host = document.getElementById(id);
  for (let i = 0; i < 20 && !host; i++) {
    await new Promise((resolve) => requestAnimationFrame(resolve));
    host = document.getElementById(id);
  }
  if (!host || host.shadowRoot) {
    return;
  }
  const root = host.attachShadow({ mode: "open" });
  const style = document.createElement("style");
  style.textContent = STYLES + TOOLTIP_STYLES;
  const body = el("div", { class: "tip" });
  root.append(style, body);
  await fillCard(body, link, item);
}

/**
 * Where something the document shows came from, and how to fix what's
 * wrong with it, as its hover card and the sidebar show it.
 */
async function fillCard(
  body: HTMLElement,
  link: OverleafLinkPublic,
  item: EditorCitation,
): Promise<void> {
  clear(body).append(loading());
  try {
    const provenance = await citationProvenance(link, item.citation);
    clear(body);
    renderProvenance(body, link, item.citation, provenance, false);
    body.append(bringUpToDate(link, item.citation, provenance));
  } catch (e) {
    clear(body).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
}

/**
 * A way to bring what the document shows up to date from its card: syncing
 * what the project already has, or running what's stale first, which syncs
 * when it's done.
 */
function bringUpToDate(
  link: OverleafLinkPublic,
  citation: Citation,
  provenance: Provenance,
): HTMLElement {
  const path = provenance.path;
  // What the next sync would bring, by where Overleaf gets its copy
  const status =
    lastCheck && linkKey(lastCheck.link) === linkKey(link)
      ? lastCheck.status
      : null;
  const waiting = (status?.files_to_push ?? []).some(
    (f) =>
      f.project_path === path ||
      f.project_path.endsWith(`/_calkit/${path}`) ||
      (citation.kind === "value" &&
        f.project_path.endsWith("/_calkit/values.tex")),
  );
  // A frozen stage won't rerun, and a manual step needs a person
  const stale =
    provenance.stale_reason === "pipeline" &&
    provenance.stage_kind !== "manual-step";
  if (stale) {
    return renderRuns(link, true);
  }
  const box = el("div", { style: { marginTop: "6px" } });
  if (waiting) {
    const { button, message } = syncNow(link, link.path);
    box.append(el("div", { class: "actions" }, [button]), message);
  }
  return box;
}

/**
 * Hear from the editor, through the script in the page's world, what the
 * open document shows and when a tooltip opens over it.
 *
 * The page can post these too, so all they can do is have the linked
 * project's provenance looked up and shown, which the page could show
 * anyway.
 */
function watchEditor(): void {
  const listener = (event: MessageEvent) => {
    if (event.source !== window || event.data?.calkit !== "editor") {
      return;
    }
    // Cut off by the extension reloading, so the script put in after
    // answers instead, rather than this one taking a tooltip it can't fill
    if (!isExtensionAlive()) {
      window.removeEventListener("message", listener);
      return;
    }
    const message = event.data as FromEditor;
    if (message.type === "citations") {
      editorCitations = { version: message.version, items: message.items };
      drawRail();
      void checkCitations();
      // The open file changed, and maybe its comments with it
      scheduleReviewThreads();
      // Overleaf saves edits as they're made, so they're there to sync
      if (lastEditorVersion !== null && message.version !== lastEditorVersion) {
        recheckAfterEdit(5000);
      }
      lastEditorVersion = message.version;
    } else if (message.type === "tooltip") {
      void fillTooltip(message.id, message.version, message.index);
    } else if (
      message.type === "text" ||
      message.type === "replaced" ||
      message.type === "tree"
    ) {
      editorReplies.get(message.reqId)?.(message);
      editorReplies.delete(message.reqId);
    }
  };
  window.addEventListener("message", listener);
  // What the open document shows, in case this script came in after the
  // editor last said
  toEditor({ type: "rescan" });
}

type SynctexBox = Omit<PdfBox, "message" | "options" | "textLeft" | "text">;

/** The PDF Overleaf last built, which synctex lookups have to name. */
interface PdfBuild {
  buildId: string;
  /** Overleaf's lookups fail without it once its URLs carry one. */
  editorId: string | null;
  clsiServerId: string | null;
}

let pdfBuild: PdfBuild | null = null;
let pdfBoxes: PdfBox[] = [];
const synctexCache = new Map<string, Promise<SynctexBox[]>>();

/** The open document's path in the Overleaf project, from the file tree. */
function openDocPath(): string | null {
  const selected = document.querySelector<HTMLElement>(
    '[role="treeitem"][aria-selected="true"]',
  );
  const name = selected?.getAttribute("aria-label");
  if (!selected || !name || !/\.tex$/i.test(name)) {
    return null;
  }
  const parts = [name];
  let folder = selected.parentElement?.closest('[role="treeitem"]');
  while (folder) {
    parts.unshift(folder.getAttribute("aria-label") ?? "");
    folder = folder.parentElement?.closest('[role="treeitem"]');
  }
  return parts.join("/");
}

// Overleaf's synctex wants an editor ID, but a build in a user's own zone
// doesn't belong to one, so any will do for those
const ANY_EDITOR_ID = crypto.randomUUID();

function setBuildParams(params: URLSearchParams, build: PdfBuild): void {
  params.set("buildId", build.buildId);
  params.set("editorId", build.editorId ?? ANY_EDITOR_ID);
  if (build.clsiServerId) {
    params.set("clsiserverid", build.clsiServerId);
  }
}

/** Where in the PDF a line of the open document landed, as Overleaf says. */
function synctex(
  projectId: string,
  build: PdfBuild,
  file: string,
  line: number,
  column: number,
): Promise<SynctexBox[]> {
  const params = new URLSearchParams({
    file,
    line: String(line),
    column: String(column),
  });
  setBuildParams(params, build);
  const key = params.toString();
  let cached = synctexCache.get(key);
  if (!cached) {
    cached = fetch(`/project/${projectId}/sync/code?${params}`, {
      headers: { Accept: "application/json" },
    })
      .then((response) => (response.ok ? response.json() : { pdf: [] }))
      .then((data: { pdf?: Omit<SynctexBox, "line" | "column">[] }) =>
        (data.pdf ?? []).map((box) => ({ ...box, line, column })),
      )
      .catch(() => []);
    synctexCache.set(key, cached);
  }
  return cached;
}

/** Find where each error in the open document lands in the PDF. */
async function drawPdfBoxes(): Promise<void> {
  const build = pdfBuild;
  const snapshot = editorCitations;
  const problems = editorProblems;
  const projectId = currentProjectId;
  const file = openDocPath();
  if (
    !build ||
    !snapshot ||
    !projectId ||
    !file ||
    problems?.version !== snapshot.version
  ) {
    return;
  }
  const boxes: PdfBox[] = [];
  for (const [index, item] of snapshot.items.entries()) {
    const error = problems.found[index]?.find((p) => p.severity === "error");
    if (!error) {
      continue;
    }
    const found = await synctex(projectId, build, file, item.line, item.column);
    // Overleaf repeats boxes, and puts the line's box around a figure's,
    // so only the innermost of each is kept
    const inside = (a: SynctexBox, b: SynctexBox) =>
      a.page === b.page &&
      a.h >= b.h &&
      a.h + a.width <= b.h + b.width &&
      a.v - a.height >= b.v - b.height &&
      a.v <= b.v;
    const kept: SynctexBox[] = [];
    for (const box of found) {
      if (
        !kept.some((k) => inside(k, box)) &&
        !found.some(
          (other) => other !== box && inside(other, box) && !inside(box, other),
        )
      ) {
        kept.push(box);
      }
    }
    const { citation } = item;
    // The value as shown, which is somewhere in its line's box
    const provenance =
      citation.kind === "value" && currentLink
        ? await citationProvenance(currentLink, citation).catch(() => null)
        : null;
    const text =
      provenance && !provenance.value_error && provenance.value !== undefined
        ? getShownValue(provenance.value, citation.options)
        : undefined;
    for (const box of kept) {
      const same = boxes.find(
        (b) =>
          b.page === box.page &&
          b.h === box.h &&
          b.v === box.v &&
          b.text === text,
      );
      if (same) {
        if (!same.message.includes(error.message)) {
          same.message += `; ${error.message}`;
        }
        continue;
      }
      boxes.push({
        ...box,
        message: error.message,
        options: citation.kind === "figure" ? citation.options : undefined,
        textLeft: Math.min(...found.map((b) => b.h)),
        text,
      });
    }
  }
  if (pdfBuild !== build || editorCitations !== snapshot) {
    return;
  }
  pdfBoxes = boxes;
  showPdfBoxes();
}

/**
 * Draw what's wrong on Overleaf's PDF, and on the viewer with comments
 * when it's showing Overleaf's.
 */
function showPdfBoxes(): void {
  const goTo = (box: PdfBox) =>
    toEditor({ type: "goto", line: box.line, column: box.column });
  placePdfBoxes(pdfBoxes, goTo);
  if (review?.ready && !review.local) {
    postToReview({ type: "boxes", boxes: pdfBoxes });
  }
}

// What's under the pointer on the viewer with comments, shown as on
// Overleaf's, or null once it's off the PDF
let pdfPointer: (
  point: {
    page: number;
    h: number;
    v: number;
    clientX: number;
    clientY: number;
  } | null,
) => void = () => undefined;

/** Follow Overleaf's builds and its PDF viewer, to keep the boxes on it. */
function watchPdf(): void {
  // A new build means new positions, and a lookup that failed for
  // want of the editor ID shouldn't stay cached
  const noteBuild = (url: string, clsiServerId: string | null) => {
    // e.g., build/<editor id>-<build id>/output/output.pdf, where the
    // editor ID, a UUID, isn't always there
    const match = url.match(
      /\/build\/(?:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})-)?([0-9a-f]+-[0-9a-f]+)\/output\/(?:cached\/)?output\.pdf/,
    );
    if (!match) {
      return;
    }
    const [, editorId = null, buildId] = match;
    const same = buildId === pdfBuild?.buildId ? pdfBuild : null;
    const next = {
      buildId,
      editorId: editorId ?? same?.editorId ?? null,
      clsiServerId: clsiServerId ?? same?.clsiServerId ?? null,
    };
    if (
      same &&
      same.editorId === next.editorId &&
      same.clsiServerId === next.clsiServerId
    ) {
      return;
    }
    pdfBuild = next;
    synctexCache.clear();
    void drawPdfBoxes();
    void sendOverleafPdf();
  };
  // Overleaf's own requests say which compile server has the build, but
  // a content script may not see them, so the PDF's download link, which
  // it always can, says which build it is
  new PerformanceObserver((list) => {
    for (const entry of list.getEntries()) {
      noteBuild(
        entry.name,
        URL.canParse(entry.name)
          ? new URL(entry.name).searchParams.get("clsiserverid")
          : null,
      );
    }
  }).observe({ type: "resource", buffered: true });
  const noteDownloadLink = () => {
    const link = document.querySelector<HTMLAnchorElement>(
      'a[href*="/build/"][href*="output.pdf"]',
    );
    if (link) {
      noteBuild(link.href, null);
    }
  };
  noteDownloadLink();
  let timer: ReturnType<typeof setTimeout> | undefined;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      noteDownloadLink();
      showPdfBoxes();
    }, 200);
  }).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["href"],
  });
  // A component's provenance on hover, as in the editor. Where each one
  // lands is asked of Overleaf once per build and edit, the first time the
  // pointer rests on the PDF, so moving it around costs nothing, and the
  // PDF still gets every click
  let shown: { index: number; version: number; host: HTMLElement } | null =
    null;
  let showing: ReturnType<typeof setTimeout> | undefined;
  let hiding: ReturnType<typeof setTimeout> | undefined;
  let lookups = 0;
  let tips = 0;
  let landed: {
    build: PdfBuild;
    snapshot: NonNullable<typeof editorCitations>;
    file: string;
    boxes: Promise<{ index: number; box: SynctexBox }[]>;
  } | null = null;
  const hide = () => {
    clearTimeout(hiding);
    hiding = undefined;
    shown?.host.remove();
    shown = null;
  };
  const citationAt = async (page: number, h: number, v: number) => {
    const build = pdfBuild;
    const projectId = currentProjectId;
    const snapshot = editorCitations;
    const file = openDocPath();
    // Only a paper linked to a project has anything to show
    if (!currentLink || !build || !projectId || !snapshot || !file) {
      return null;
    }
    if (
      landed?.build !== build ||
      landed.snapshot !== snapshot ||
      landed.file !== file
    ) {
      // One at a time, and cached by line, so an edit only asks again
      // about what moved
      const boxes = (async () => {
        const found: { index: number; box: SynctexBox }[] = [];
        for (const [index, item] of snapshot.items.entries()) {
          if (!item.citation) {
            continue;
          }
          for (const box of await synctex(
            projectId,
            build,
            file,
            item.line,
            item.column,
          )) {
            found.push({ index, box });
          }
        }
        return found;
      })();
      landed = { build, snapshot, file, boxes };
    }
    // The smallest box under the pointer, e.g., a figure's rather than the
    // line's around it; a box's v is its bottom
    let best: { index: number; area: number } | null = null;
    for (const { index, box } of await landed.boxes) {
      const area = box.width * box.height;
      if (
        box.page === page &&
        h >= box.h &&
        h <= box.h + box.width &&
        v >= box.v - box.height &&
        v <= box.v &&
        (!best || area < best.area)
      ) {
        best = { index, area };
      }
    }
    return best ? { index: best.index, version: snapshot.version } : null;
  };
  const show = (
    found: { index: number; version: number },
    x: number,
    y: number,
  ) => {
    hide();
    const host = el("div");
    host.id = `calkit-pdf-tooltip-${++tips}`;
    const below = y < window.innerHeight / 2;
    Object.assign(host.style, {
      position: "fixed",
      left: `${Math.max(4, Math.min(x - 20, window.innerWidth - 386))}px`,
      ...(below
        ? { top: `${y + 12}px` }
        : { bottom: `${window.innerHeight - y + 12}px` }),
      zIndex: "2147483646",
      border: "1px solid rgba(0, 0, 0, 0.15)",
      borderRadius: "4px",
      boxShadow: "0 2px 8px rgba(0, 0, 0, 0.2)",
      overflow: "hidden",
    });
    document.body.append(host);
    shown = { ...found, host };
    void fillTooltip(host.id, found.version, found.index);
  };
  // Over the PDF, what's under the pointer once it rests decides, whether
  // it's Overleaf's viewer or the one with comments
  const pointAt = (point: {
    page: number;
    h: number;
    v: number;
    clientX: number;
    clientY: number;
  }) => {
    clearTimeout(showing);
    clearTimeout(hiding);
    hiding = undefined;
    showing = setTimeout(async () => {
      const lookup = ++lookups;
      const found = await citationAt(point.page, point.h, point.v);
      if (lookup !== lookups) {
        return;
      }
      if (!found) {
        hide();
      } else if (
        shown?.index !== found.index ||
        shown.version !== found.version
      ) {
        show(found, point.clientX, point.clientY);
      }
    }, 300);
  };
  pdfPointer = (point) => {
    if (point) {
      pointAt(point);
      return;
    }
    clearTimeout(showing);
    if (shown && hiding === undefined) {
      hiding = setTimeout(hide, 300);
    }
  };
  document.addEventListener(
    "mousemove",
    (event) => {
      clearTimeout(showing);
      if (shown && event.target === shown.host) {
        clearTimeout(hiding);
        hiding = undefined;
        return;
      }
      const page = (event.target as Element | null)?.closest?.<HTMLElement>(
        ".pdfViewer .page[data-page-number]",
      );
      const scale = page
        ? parseFloat(getComputedStyle(page).getPropertyValue("--scale-factor"))
        : NaN;
      if (!page || !Number.isFinite(scale)) {
        if (shown && hiding === undefined) {
          hiding = setTimeout(hide, 300);
        }
        return;
      }
      const bounds = page.getBoundingClientRect();
      pointAt({
        page: Number(page.dataset.pageNumber),
        h: (event.clientX - bounds.left - page.clientLeft) / scale,
        v: (event.clientY - bounds.top - page.clientTop) / scale,
        clientX: event.clientX,
        clientY: event.clientY,
      });
    },
    { passive: true },
  );
  // A fixed tooltip would stay put while the PDF scrolls away under it
  document.addEventListener(
    "scroll",
    (event) => {
      if (shown && event.target !== shown.host) {
        clearTimeout(showing);
        hide();
      }
    },
    { capture: true, passive: true },
  );
}

/**
 * Insert a figure, table, or value from the project at the cursor.
 *
 * What's inserted is a calkit.sty command naming it by its path in the
 * project. The next sync brings what it cites into the paper's _calkit
 * folder, so there's nothing to set up: no map-paths or json-to-latex
 * stage, and no copying files by hand.
 */
function renderInsert(
  link: OverleafLinkPublic,
  path: string,
  reload: () => void,
): HTMLElement {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const list = el("div", { class: "stack", style: { marginTop: "6px" } });
  const message = el("div", { class: "small" });
  const format = textInput({ placeholder: "Format, e.g., .2f (optional)" });
  const insert = async (citation: Citation) => {
    try {
      const how = await insertIntoEditor(citationText(citation));
      const sync = async () => {
        clear(message).append(loading("Syncing"));
        // Overleaf saves an edit a moment after it's made, and a sync
        // started first would miss it
        await new Promise((resolve) => setTimeout(resolve, 3000));
        try {
          await syncOverleaf(owner, project, path);
          reload();
        } catch (e) {
          clear(message).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
        }
      };
      // Synced right away so it shows up, unless it still has to be pasted
      if (how === "inserted") {
        await sync();
        return;
      }
      clear(message).append(
        el("div", {
          class: "dim small",
          text:
            "Copied; paste it where it should go, then sync to bring it " +
            "into the paper. The document needs \\usepackage{calkit} in " +
            "its preamble.",
        }),
        el("div", { class: "actions" }, [
          el("button", {
            class: "action secondary",
            text: "Sync now",
            onClick: (e: Event) => {
              (e.currentTarget as HTMLButtonElement).disabled = true;
              void sync();
            },
          }),
        ]),
      );
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  };
  const row = (title: string, detail: string, onClick: () => void) =>
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        el("div", { class: "small", text: title }),
        el("div", { class: "dim small", text: detail }),
      ]),
      el("button", {
        class: "action secondary",
        text: "Insert",
        onClick,
      }),
    ]);
  const showFigures = async () => {
    clear(list).append(loading());
    try {
      const page = await send({ type: "project.figures", owner, project });
      clear(list);
      for (const figure of page.items) {
        list.append(
          row(figure.title, figure.path, () =>
            insert({
              kind: "figure",
              path: figure.path,
              options: "width=\\linewidth",
            }),
          ),
        );
      }
      if (!page.items.length) {
        list.append(el("div", { class: "dim small", text: "No figures" }));
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  const showTables = async () => {
    clear(list).append(loading());
    try {
      // \cktable inputs TeX, so a CSV would need a stage to typeset it
      const tables = (
        await send({ type: "project.tables", owner, project })
      ).filter((table) => table.path.endsWith(".tex"));
      clear(list);
      for (const table of tables) {
        list.append(
          row(table.title, table.path, () =>
            insert({ kind: "table", path: table.path, options: "" }),
          ),
        );
      }
      if (!tables.length) {
        list.append(
          el("div", {
            class: "dim small",
            text: "No tables written as TeX",
          }),
        );
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  // A value is picked from inside a results file, so a file opens to its
  // keys rather than inserting anything
  const showValues = async () => {
    clear(list).append(loading());
    try {
      const results = await send({ type: "project.results", owner, project });
      const paths = [...new Set(results.map((result) => result.path))].filter(
        (resultPath) => /\.(json|ya?ml|toml)$/i.test(resultPath),
      );
      clear(list).append(format);
      for (const resultPath of paths) {
        const keys = el("div", { style: { paddingLeft: "10px" } });
        const open = el("button", {
          class: "action secondary",
          text: "Open",
        });
        open.addEventListener("click", async () => {
          open.disabled = true;
          clear(keys).append(loading());
          try {
            const file = await provenanceFor(link, resultPath);
            clear(keys);
            if (file.value_error) {
              keys.append(errorMessage(file.value_error));
              return;
            }
            // Every leaf, by its dotted key, which is what \ckvalue takes
            const walk = (value: unknown, prefix: string) => {
              if (value === null || typeof value !== "object") {
                keys.append(
                  row(prefix, valueText(value), () =>
                    insert({
                      kind: "value",
                      path: resultPath,
                      key: prefix,
                      options: format.value.trim(),
                    }),
                  ),
                );
                return;
              }
              const entries = Array.isArray(value)
                ? value.map((item, i) => [String(i), item] as const)
                : Object.entries(value as Record<string, unknown>);
              for (const [name, item] of entries) {
                walk(item, prefix ? `${prefix}.${name}` : name);
              }
            };
            walk(file.value, "");
          } catch (e) {
            open.disabled = false;
            clear(keys).append(
              errorMessage(e instanceof Error ? e.message : String(e)),
            );
          }
        });
        list.append(
          el("div", { class: "row" }, [
            el("div", { class: "grow small", text: resultPath }),
            open,
          ]),
          keys,
        );
      }
      if (!paths.length) {
        list.append(
          el("div", {
            class: "dim small",
            text: "No JSON, YAML, or TOML results",
          }),
        );
      }
    } catch (e) {
      clear(list).append(renderFailure(e, { onSignedIn: reload }));
    }
  };
  return el("div", { style: { marginTop: "10px" } }, [
    el("div", {
      class: "small",
      style: { fontWeight: "600" },
      text: "Insert from the project",
    }),
    el("div", { class: "actions" }, [
      el("button", {
        class: "action secondary",
        text: "Figure",
        onClick: () => void showFigures(),
      }),
      el("button", {
        class: "action secondary",
        text: "Table",
        onClick: () => void showTables(),
      }),
      el("button", {
        class: "action secondary",
        text: "Value",
        onClick: () => void showValues(),
      }),
    ]),
    list,
    message,
  ]);
}

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
  const get = el("button", {
    class: "action",
    text: "Get a token from Overleaf",
  });
  get.addEventListener("click", async () => {
    try {
      await send({ type: "overleaf.openTokenSettings" });
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  const save = el("button", {
    class: "action secondary",
    text: "Save token",
  });
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
      document.createTextNode(
        "Opens your Overleaf settings, where you click Generate token. " +
          "Calkit saves it and brings you back here.",
      ),
    ]),
    el("div", { class: "actions" }, [get]),
    el("div", { class: "dim small", style: { marginTop: "12px" } }, [
      document.createTextNode("Or paste one you have:"),
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
 * Save an Overleaf Git token to Calkit as soon as Overleaf shows one, which
 * it only does once, right after it's generated.
 *
 * In a tab the Calkit panel opened for this, the user already asked for the
 * token to be saved, so it is, and they go back to their project. Anywhere
 * else it's only offered: nothing is read or sent until they click.
 */
async function watchForNewToken(): Promise<void> {
  if (tokenWatcher) {
    return;
  }
  // Set now so a second sync doesn't start another while this one asks
  const placeholder = new MutationObserver(() => undefined);
  tokenWatcher = placeholder;
  const { requested } = await send({ type: "overleaf.tokenTab" }).catch(() => ({
    requested: false,
  }));
  if (tokenWatcher !== placeholder) {
    // Torn down meanwhile
    return;
  }
  const texts = (): string[] => [
    ...Array.from(document.querySelectorAll("input"), (input) => input.value),
    document.body.innerText,
  ];
  const message = el("div", { class: "small" });
  const save = async (tokenPanel: Panel): Promise<void> => {
    const token = texts()
      .map((text) => text.match(OVERLEAF_TOKEN_RE)?.[0])
      .find(Boolean);
    if (!token) {
      clear(message).append(errorMessage("The token is no longer on the page"));
      return;
    }
    clear(message).append(loading("Saving"));
    try {
      await send({ type: "overleaf.setToken", token });
    } catch (e) {
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
      return;
    }
    clear(tokenPanel.body).append(
      el("div", {
        class: "small",
        text: "Saved. Your Overleaf projects can sync with Calkit now.",
      }),
    );
    if (requested) {
      await send({ type: "overleaf.returnFromTokenTab" }).catch(
        () => undefined,
      );
    }
  };
  // Point at the button that makes one, which Overleaf labels by whether
  // the account has a token already
  let pointed = false;
  const pointAtGenerate = (): void => {
    const button = Array.from(document.querySelectorAll("button")).find((b) =>
      /^\s*(generate token|add another token)\s*$/i.test(b.textContent ?? ""),
    );
    if (!button) {
      return;
    }
    pointed = true;
    button.scrollIntoView({ block: "center" });
    button.style.outline = "3px solid #f0ad4e";
    button.style.outlineOffset = "2px";
  };
  const guide = requested
    ? mountPanel({ id: TOKEN_PANEL_ID, title: "Calkit" })
    : null;
  if (guide) {
    guide.body.append(
      el("div", {
        class: "small",
        text:
          "Click Generate token under Git integration. Calkit saves the " +
          "token and takes you back to your project.",
      }),
      message,
    );
    pointAtGenerate();
  }
  // Only whether one is showing until it's saved, so the token itself is
  // never held before then
  let showing = false;
  tokenWatcher = new MutationObserver(() => {
    if (requested && !pointed) {
      pointAtGenerate();
    }
    const visible = texts().some((text) => OVERLEAF_TOKEN_RE.test(text));
    if (visible === showing) {
      return;
    }
    showing = visible;
    if (guide) {
      if (visible) {
        void save(guide);
      }
      return;
    }
    if (!visible) {
      document.getElementById(TOKEN_PANEL_ID)?.remove();
      return;
    }
    const tokenPanel = mountPanel({ id: TOKEN_PANEL_ID, title: "Calkit" });
    const button = el("button", { class: "action", text: "Save to Calkit" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      await save(tokenPanel);
      button.disabled = false;
    });
    clear(message);
    tokenPanel.body.append(
      el("div", {
        class: "small",
        text:
          "Save this Overleaf Git token to Calkit, so it can check and " +
          "sync your Overleaf projects?",
      }),
      el("div", { class: "actions" }, [button]),
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

// The PDF from this computer shown over Overleaf's, if it is
let localPdf: {
  host: HTMLElement;
  link: OverleafLinkPublic;
  path: string;
} | null = null;

/**
 * Show the PDF a synced folder builds to on this computer, e.g., from a
 * pipeline run, over Overleaf's, so there's no waiting on Overleaf to
 * compile, until it's turned off. Overleaf's own PDF features, e.g.,
 * double-clicking to go to the source, don't work in it.
 */
function showLocalPdf(link: OverleafLinkPublic, path: string): void {
  hideLocalPdf();
  const pane = getPdfPane();
  if (!pane) {
    return;
  }
  const params = new URLSearchParams({
    localProject: `${link.project_owner_name}/${link.project_name}`,
    folder: path,
  });
  const frame = el("iframe", {
    title: "PDF from this computer",
    style: { flex: "1", width: "100%", border: "none", background: "#fff" },
  });
  // Always with comments, whose own toggle hides them, since without them
  // it would be the browser's plain viewer
  frame.src = getReviewUrl(params);
  // The switch in Overleaf's toolbar says which PDF this is
  const host = el("div", {}, [frame]);
  Object.assign(host.style, {
    display: "flex",
    flexDirection: "column",
    background: "#fff",
    position: "absolute",
    inset: "0",
    zIndex: "20",
  });
  if (getComputedStyle(pane).position === "static") {
    pane.style.position = "relative";
  }
  pane.append(host);
  localPdf = { host, link, path };
  hideOverleafReview();
  review = { frame, host, local: true, ready: false, buildId: null };
  mountPdfSwitch();
  mountCommentsToggle();
}

function hideLocalPdf(): void {
  localPdf?.host.remove();
  localPdf = null;
  if (review?.local) {
    review = null;
  }
  mountPdfSwitch();
  mountCommentsToggle();
  if (commentsOn) {
    showOverleafReview();
  }
}

// Whether the PDF is shown with its comments, in the viewer that has
// them, for this Overleaf project
let commentsOn = false;
/** Whether someone last showed comments on an Overleaf project, by ID. */
const COMMENTS_KEY = "pdfComments";

// The viewer with comments over Overleaf's PDF pane, if it's shown
let review: {
  frame: HTMLIFrameElement;
  host: HTMLElement;
  /** Showing the PDF built on this computer, rather than Overleaf's. */
  local: boolean;
  ready: boolean;
  /** The build of Overleaf's PDF it has. */
  buildId: string | null;
} | null = null;

// The project's LaTeX source as the PDF was built from it, and as it is
// now, which the threads and where they are in the PDF come from
let reviewSources: {
  buildId: string | null;
  built: Map<string, string>;
  current: Map<string, string>;
} | null = null;

// Answers from the editor's script, by request
const editorReplies = new Map<
  number,
  (message: FromEditor & { type: "text" | "replaced" | "tree" }) => void
>();
let editorRequests = 0;

/** The open file's text in the editor, or null if there isn't one. */
function readEditor(): Promise<string | null> {
  const reqId = ++editorRequests;
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      editorReplies.delete(reqId);
      resolve(null);
    }, 3000);
    editorReplies.set(reqId, (message) => {
      clearTimeout(timer);
      resolve(message.type === "text" ? message.text : null);
    });
    toEditor({ type: "read", reqId });
  });
}

/**
 * What the Overleaf project has, from its editor: every file's Git hash
 * and the documents' text, by path, so Calkit on this computer can tell if
 * its copy is current, or bring it up to date, without downloading the
 * project. Null if Overleaf's file tree can't be read.
 */
async function getOverleafFiles(projectId: string): Promise<{
  shas: Record<string, string>;
  texts: Record<string, string>;
} | null> {
  const reqId = ++editorRequests;
  const tree = await new Promise<(FromEditor & { type: "tree" })["tree"]>(
    (resolve) => {
      const timer = setTimeout(() => {
        editorReplies.delete(reqId);
        resolve(null);
      }, 3000);
      editorReplies.set(reqId, (message) => {
        clearTimeout(timer);
        resolve(message.type === "tree" ? message.tree : null);
      });
      toEditor({ type: "tree", reqId });
    },
  );
  if (!tree) {
    return null;
  }
  const shas: Record<string, string> = {};
  const texts: Record<string, string> = {};
  for (const file of tree.files) {
    shas[file.path] = file.hash;
  }
  try {
    await Promise.all(
      tree.docs.map(async (doc) => {
        const response = await fetch(
          `/project/${projectId}/doc/${doc.id}/download`,
        );
        if (!response.ok) {
          throw new Error(`Couldn't read ${doc.path} (${response.status})`);
        }
        const data = new Uint8Array(await response.arrayBuffer());
        shas[doc.path] = await getGitBlobSha(data);
        texts[doc.path] = new TextDecoder().decode(data);
      }),
    );
  } catch {
    return null;
  }
  return { shas, texts };
}

/** Make an edit to the open file in the editor, as typing would. */
function editEditor(edit: LineEdit, lines: string[]): Promise<void> {
  const reqId = ++editorRequests;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      editorReplies.delete(reqId);
      reject(new Error("The editor didn't answer."));
    }, 3000);
    editorReplies.set(reqId, (message) => {
      clearTimeout(timer);
      if (message.type === "replaced" && message.error) {
        reject(new Error(message.error));
      } else {
        resolve();
      }
    });
    toEditor({
      type: "replace",
      reqId,
      line: edit.line,
      expected: lines.slice(edit.line - 1, edit.line - 1 + edit.count),
      insert: edit.insert,
    });
  });
}

/**
 * Open a file in Overleaf's editor, as clicking it in the file tree would,
 * opening the folders it's in first, and wait for it to load. Says whether
 * it could.
 */
async function openDocument(path: string): Promise<boolean> {
  const sleep = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  if (openDocPath() === path) {
    return true;
  }
  const parts = path.split("/");
  let scope: ParentNode = document;
  for (const [i, name] of parts.entries()) {
    const item = [
      ...scope.querySelectorAll<HTMLElement>('[role="treeitem"]'),
    ].find((node) => node.getAttribute("aria-label") === name);
    if (!item) {
      return false;
    }
    if (i < parts.length - 1) {
      if (item.getAttribute("aria-expanded") === "false") {
        item
          .querySelector<HTMLElement>(".folder-expand-collapse-button")
          ?.click();
        await sleep(300);
      }
      scope = item;
      continue;
    }
    (
      item.querySelector<HTMLElement>(".file-tree-entity-button") ?? item
    ).click();
  }
  for (let i = 0; i < 50 && openDocPath() !== path; i++) {
    await sleep(100);
  }
  // The editor shows it a moment after the tree says it's open
  await sleep(300);
  return openDocPath() === path;
}

/** Who's commenting, as Overleaf knows them. */
function getCommentAuthor(): CommentAuthor {
  try {
    const user = JSON.parse(
      document.querySelector<HTMLMetaElement>('meta[name="ol-user"]')
        ?.content ?? "{}",
    );
    const name = [user.first_name, user.last_name]
      .filter(Boolean)
      .join(" ")
      .trim();
    return { name: name || user.email || "Someone", email: user.email ?? null };
  } catch {
    return { name: "Someone", email: null };
  }
}

/**
 * The text of the project's LaTeX files, except the ones Calkit writes:
 * each on its own where the file tree shows its ID, else all from the
 * project's download, e.g., for one in a folder that's closed.
 */
async function getOverleafTexts(
  projectId: string,
): Promise<Map<string, string>> {
  const response = await fetch(`/project/${projectId}/entities`);
  if (!response.ok) {
    throw new Error(`Couldn't list the project's files (${response.status})`);
  }
  const { entities } = (await response.json()) as {
    entities: { path: string; type: string }[];
  };
  const wanted = (path: string) =>
    /\.tex$/i.test(path) && !path.startsWith("_calkit/");
  const paths = entities
    .filter((e) => e.type === "doc")
    .map((e) => e.path.replace(/^\//, ""))
    .filter(wanted);
  const ids = getDocIds();
  if (paths.every((p) => ids.get(p))) {
    const texts = await Promise.all(
      paths.map(async (p) => {
        const doc = await fetch(
          `/project/${projectId}/doc/${ids.get(p)}/download`,
        );
        if (!doc.ok) {
          throw new Error(`Couldn't read ${p} (${doc.status})`);
        }
        return [p, await doc.text()] as const;
      }),
    );
    return new Map(texts);
  }
  const zip = await fetch(`/project/${projectId}/download/zip`);
  if (!zip.ok) {
    throw new Error(`Couldn't download the project (${zip.status})`);
  }
  return getZipTexts(await zip.arrayBuffer(), wanted);
}

/**
 * The IDs of the documents the file tree shows, by their paths. Those in
 * closed folders aren't shown.
 */
function getDocIds(): Map<string, string> {
  const ids = new Map<string, string>();
  for (const node of document.querySelectorAll<HTMLElement>(
    '[data-file-type="doc"][data-file-id]',
  )) {
    const parts: string[] = [];
    let item = node.closest('[role="treeitem"]');
    while (item) {
      parts.unshift(item.getAttribute("aria-label") ?? "");
      item = item.parentElement?.closest('[role="treeitem"]') ?? null;
    }
    ids.set(parts.join("/"), node.dataset.fileId ?? "");
  }
  return ids;
}

/**
 * The comments made on Overleaf, by the file each is in, and their
 * threads. A file the tree doesn't show is found by the comments' text
 * being where they say.
 */
async function getOverleafComments(
  projectId: string,
  texts: Map<string, string>,
): Promise<{
  byFile: Map<string, OverleafComment[]>;
  threads: Record<string, OverleafThread>;
}> {
  const read = async <T>(path: string): Promise<T> => {
    const response = await fetch(`/project/${projectId}/${path}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Couldn't read Overleaf's comments (${response.status})`);
    }
    return response.json();
  };
  const [ranges, threads] = await Promise.all([
    read<
      {
        id: string;
        ranges?: { comments?: { op: { c: string; p: number; t: string } }[] };
      }[]
    >("ranges"),
    read<Record<string, OverleafThread>>("threads"),
  ]);
  const paths = new Map([...getDocIds()].map(([path, id]) => [id, path]));
  const byFile = new Map<string, OverleafComment[]>();
  for (const doc of ranges) {
    const comments = (doc.ranges?.comments ?? []).map(({ op }) => ({
      thread: op.t,
      text: op.c,
      offset: op.p,
    }));
    if (!comments.length) {
      continue;
    }
    const path =
      paths.get(doc.id) ??
      [...texts].find(([, text]) =>
        comments.every(
          (c) => text.slice(c.offset, c.offset + c.text.length) === c.text,
        ),
      )?.[0];
    if (path) {
      byFile.set(path, comments);
    }
  }
  return { byFile, threads };
}

/** Delete a comment thread on Overleaf, as its review panel does. */
async function deleteOverleafThread(
  projectId: string,
  docId: string,
  thread: string,
): Promise<void> {
  const response = await fetch(
    `/project/${projectId}/doc/${docId}/thread/${thread}`,
    {
      method: "DELETE",
      headers: {
        Accept: "application/json",
        "X-Csrf-Token":
          document.querySelector<HTMLMetaElement>('meta[name="ol-csrfToken"]')
            ?.content ?? "",
      },
    },
  );
  // Already gone is as good as deleted
  if (!response.ok && response.status !== 404) {
    throw new Error(
      `Overleaf didn't delete the comment thread (${response.status})`,
    );
  }
}

/** How each Overleaf thread was when last in step, by Overleaf project. */
const OVERLEAF_SYNCED_KEY = "overleafCommentsSynced";

/**
 * Bring the open file's Overleaf comments into its source, through the
 * editor, and remember how each thread now is. Only the open one, so
 * someone's file isn't switched under them; each catches up when opened.
 * Says whether the source changed.
 */
async function syncOverleafComments(
  projectId: string,
  file: string,
  sources: { current: Map<string, string> },
): Promise<boolean> {
  const { byFile, threads } = await getOverleafComments(
    projectId,
    sources.current,
  );
  const lines = (sources.current.get(file) ?? "").split("\n");
  const comments = byFile.get(file) ?? [];
  if (!comments.length && !lines.some((l) => /overleaf=/.test(l))) {
    return false;
  }
  const stored = (await chrome.storage.local.get(OVERLEAF_SYNCED_KEY))[
    OVERLEAF_SYNCED_KEY
  ] as Record<string, Record<string, OverleafSynced>> | undefined;
  const known = stored?.[projectId] ?? {};
  const {
    lines: next,
    pushes,
    synced,
  } = getOverleafSyncedLines(
    lines,
    comments,
    threads,
    known,
    getCommentAuthor().name,
  );
  // Overleaf first, so if it refuses, nothing's changed and it's tried
  // again next time
  const docId = getDocIds().get(file);
  const csrf =
    document.querySelector<HTMLMetaElement>('meta[name="ol-csrfToken"]')
      ?.content ?? "";
  const post = async (path: string, body?: object) => {
    const response = await fetch(`/project/${projectId}/${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-Csrf-Token": csrf,
      },
      body: JSON.stringify(body ?? {}),
    });
    if (!response.ok) {
      throw new Error(
        `Overleaf didn't take a change to a comment (${response.status})`,
      );
    }
  };
  for (const push of pushes) {
    if (push.deleted) {
      if (docId) {
        await deleteOverleafThread(projectId, docId, push.thread);
      }
      continue;
    }
    for (const content of push.replies) {
      await post(`thread/${push.thread}/messages`, { content });
    }
    if (push.resolved !== undefined && docId) {
      await post(
        `doc/${docId}/thread/${push.thread}/${
          push.resolved ? "resolve" : "reopen"
        }`,
      );
    }
  }
  const changed = next.join("\n") !== lines.join("\n");
  if (changed) {
    // Only what changed, so the rest of the file is left as it is
    let prefix = 0;
    while (
      prefix < lines.length &&
      prefix < next.length &&
      lines[prefix] === next[prefix]
    ) {
      prefix++;
    }
    let suffix = 0;
    while (
      suffix < lines.length - prefix &&
      suffix < next.length - prefix &&
      lines[lines.length - 1 - suffix] === next[next.length - 1 - suffix]
    ) {
      suffix++;
    }
    await editEditor(
      {
        line: prefix + 1,
        count: lines.length - prefix - suffix,
        insert: next.slice(prefix, next.length - suffix),
      },
      lines,
    );
    sources.current.set(file, next.join("\n"));
  }
  // This file's threads replace what was known of them
  const here = new Set([
    ...comments.map((c) => c.thread),
    ...getReviewThreads(new Map([[file, lines.join("\n")]])).flatMap((t) =>
      t.overleaf ? [t.overleaf] : [],
    ),
  ]);
  const kept = Object.fromEntries(
    Object.entries(known).filter(([id]) => !here.has(id)),
  );
  await chrome.storage.local.set({
    [OVERLEAF_SYNCED_KEY]: { ...stored, [projectId]: { ...kept, ...synced } },
  });
  return changed;
}

// The file whose Overleaf comments were last brought into its source
let overleafSyncedFile: string | null = null;

/** The address of the viewer with comments, for this page. */
function getReviewUrl(params: URLSearchParams): string {
  const all = new URLSearchParams(params);
  all.set("parent", window.location.origin);
  // Overleaf's own PDF toolbar and backdrop, whichever theme is on
  const toolbar = document.querySelector(".toolbar-pdf");
  const pane = toolbar?.closest(".pdf");
  if (toolbar) {
    all.set("bar", getComputedStyle(toolbar).backgroundColor);
    all.set("barText", getComputedStyle(toolbar).color);
  }
  if (pane) {
    all.set("backdrop", getComputedStyle(pane).backgroundColor);
  }
  // The panel's, from the variables Overleaf's own themed panels use
  const theme = getComputedStyle(document.body);
  for (const [param, name] of [
    ["bg", "--bg-primary-themed"],
    ["fg", "--content-primary-themed"],
    ["muted", "--content-placeholder-themed"],
    ["border", "--bg-tertiary-themed"],
    ["raised", "--bg-secondary-themed"],
    ["raisedHover", "--bg-tertiary-themed"],
  ]) {
    const color = theme.getPropertyValue(name).trim();
    if (color) {
      all.set(param, color);
    }
  }
  all.set(
    "key",
    `${currentProjectId}:${all.has("localProject") ? "local" : "overleaf"}`,
  );
  return `${chrome.runtime.getURL("review.html")}?${all}`;
}

function postToReview(
  message: Without<ToReview>,
  transfer: Transferable[] = [],
): void {
  review?.frame.contentWindow?.postMessage(
    { calkit: "review", ...message },
    new URL(chrome.runtime.getURL("")).origin,
    transfer,
  );
}

/** Show Overleaf's PDF in the viewer with comments, over its own. */
function showOverleafReview(): void {
  if (review && !review.local && review.host.isConnected) {
    return;
  }
  hideOverleafReview();
  const pane = getPdfPane();
  if (!pane || localPdf) {
    return;
  }
  const frame = el("iframe", {
    title: "PDF with comments",
    style: { flex: "1", width: "100%", border: "none", background: "#fff" },
  });
  frame.src = getReviewUrl(new URLSearchParams());
  const host = el("div", {}, [frame]);
  Object.assign(host.style, {
    display: "flex",
    flexDirection: "column",
    background: "#fff",
    position: "absolute",
    inset: "0",
    zIndex: "20",
  });
  if (getComputedStyle(pane).position === "static") {
    pane.style.position = "relative";
  }
  pane.append(host);
  review = { frame, host, local: false, ready: false, buildId: null };
}

function hideOverleafReview(): void {
  if (review && !review.local) {
    review.host.remove();
    review = null;
  }
}

/** Send the viewer Overleaf's latest PDF, if it hasn't got it. */
async function sendOverleafPdf(): Promise<void> {
  const r = review;
  const build = pdfBuild;
  if (!r?.ready || r.local || !build || r.buildId === build.buildId) {
    return;
  }
  const link = document.querySelector<HTMLAnchorElement>(
    'a[href*="/build/"][href*="output.pdf"]',
  );
  if (!link) {
    return;
  }
  r.buildId = build.buildId;
  try {
    const response = await fetch(link.href);
    if (!response.ok) {
      throw new Error(`Couldn't get the PDF (${response.status})`);
    }
    const data = await response.arrayBuffer();
    if (review !== r) {
      return;
    }
    postToReview({ type: "load", data }, [data]);
    postToReview({ type: "boxes", boxes: pdfBoxes });
    await refreshReviewThreads(true);
  } catch (e) {
    r.buildId = null;
    postToReview({
      type: "status",
      text: e instanceof Error ? e.message : String(e),
    });
  }
}

/** Where a box Overleaf's SyncTeX gives is, as the viewer measures. */
function toPdfRect(box: SynctexBox): PdfRect {
  return {
    page: box.page,
    x: box.h,
    y: box.v - box.height,
    width: box.width,
    height: box.height,
  };
}

/**
 * Send the viewer the threads in the source, with where each is in
 * Overleaf's PDF. The project's files are read again for a new build, and
 * otherwise only the open one, from the editor.
 */
async function refreshReviewThreads(full: boolean): Promise<void> {
  const r = review;
  const projectId = currentProjectId;
  if (!r?.ready || !projectId) {
    return;
  }
  try {
    let sources = reviewSources;
    const buildId = r.local ? null : pdfBuild?.buildId ?? null;
    if (full || !sources) {
      const texts = await getOverleafTexts(projectId);
      sources = {
        buildId,
        // What a build was made from is read once, when it's new
        built:
          sources && sources.buildId === buildId
            ? sources.built
            : new Map(texts),
        current: texts,
      };
      reviewSources = sources;
    }
    const file = openDocPath();
    const live = file && sources.current.has(file) ? await readEditor() : null;
    if (file && live !== null) {
      sources.current.set(file, live);
      // Overleaf's comments are asked for with a new build, or a file just
      // opened, not on every edit
      if (full || overleafSyncedFile !== file) {
        overleafSyncedFile = file;
        try {
          await syncOverleafComments(projectId, file, sources);
        } catch (e) {
          postToReview({
            type: "status",
            text: e instanceof Error ? e.message : String(e),
          });
        }
      }
    }
    const threads = getReviewThreads(sources.current);
    const build = pdfBuild;
    const synctexUsed = !r.local && Boolean(build);
    if (build && !r.local) {
      const { built, current } = sources;
      await Promise.all(
        threads.map(async (t) => {
          if (!t.anchor) {
            return;
          }
          const map = lineMap(
            (built.get(t.path) ?? "").split("\n"),
            (current.get(t.path) ?? "").split("\n"),
          );
          const [start] = await synctex(
            projectId,
            build,
            t.path,
            map.toBefore(t.anchor.line),
            0,
          );
          const ends = await synctex(
            projectId,
            build,
            t.path,
            map.toBefore(t.anchor.end_line),
            0,
          );
          if (start) {
            t.start = toPdfRect(start);
          }
          if (ends.length) {
            t.end = toPdfRect(ends[ends.length - 1]);
          }
        }),
      );
    }
    if (review === r) {
      postToReview({
        type: "threads",
        threads,
        synctex: synctexUsed,
        stale: [],
      });
    }
  } catch (e) {
    postToReview({
      type: "status",
      text: `Couldn't read the comments: ${e instanceof Error ? e.message : e}`,
    });
  }
}

let reviewTimer: ReturnType<typeof setTimeout> | undefined;
function scheduleReviewThreads(): void {
  if (!review?.ready) {
    return;
  }
  clearTimeout(reviewTimer);
  reviewTimer = setTimeout(() => void refreshReviewThreads(false), 800);
}

/**
 * The source file and line at a place in the PDF: by SyncTeX for
 * Overleaf's, else the paragraph sharing the most words with the text
 * there, as a line in the source now.
 */
async function getSourceAt(
  page: number,
  x: number,
  y: number,
  context: string,
): Promise<{
  file: string;
  line: number;
  start?: PdfRect;
  text?: string;
} | null> {
  const projectId = currentProjectId;
  const sources = reviewSources;
  const build = pdfBuild;
  if (!projectId || !sources) {
    return null;
  }
  if (review && !review.local && build) {
    const params = new URLSearchParams({
      page: String(page),
      h: String(x),
      v: String(y),
    });
    setBuildParams(params, build);
    const response = await fetch(`/project/${projectId}/sync/pdf?${params}`, {
      headers: { Accept: "application/json" },
    });
    const data = response.ok
      ? ((await response.json()) as { code?: { file: string; line: number }[] })
      : {};
    const found = data.code?.find((c) => sources.current.has(c.file));
    if (found) {
      const map = lineMap(
        (sources.built.get(found.file) ?? "").split("\n"),
        (sources.current.get(found.file) ?? "").split("\n"),
      );
      const line = map.toAfter(found.line);
      const lines = (sources.current.get(found.file) ?? "").split("\n");
      const para = paragraphLines(lines, line);
      const [box] = await synctex(
        projectId,
        build,
        found.file,
        map.toBefore(para.start),
        0,
      );
      return { file: found.file, line, start: box && toPdfRect(box) };
    }
  }
  const para = findParagraphByText(sources.current, context);
  return para && { file: para.file, line: para.line, text: para.text };
}

/**
 * Edit a file through Overleaf's editor, opening it first, so the change
 * is saved and shared like any other.
 */
async function editSource(
  file: string,
  getEdit: (lines: string[]) => LineEdit,
): Promise<LineEdit> {
  if (!(await openDocument(file))) {
    throw new Error(`Couldn't open ${file} in the editor.`);
  }
  const text = await readEditor();
  if (text === null) {
    throw new Error(`Couldn't read ${file} from the editor.`);
  }
  const lines = text.split("\n");
  const edit = getEdit(lines);
  await editEditor(edit, lines);
  reviewSources?.current.set(file, getEditedLines(lines, edit).join("\n"));
  return edit;
}

/**
 * Add a thread from the source to Overleaf's comments through Overleaf's
 * own comment form, since a comment's place in the text can only be set by
 * its editor: its text is selected, the form opened, and its first message
 * put in and sent. The next sync links the two.
 */
async function postToOverleaf(
  file: string,
  ref: { id?: string; line?: number },
  me: string,
): Promise<void> {
  const sleep = (ms: number) =>
    new Promise((resolve) => setTimeout(resolve, ms));
  if (!(await openDocument(file))) {
    throw new Error(`Couldn't open ${file} in the editor.`);
  }
  const text = (await readEditor()) ?? "";
  const lines = text.split("\n");
  const thread = getReviewThreads(new Map([[file, text]])).find((t) =>
    ref.id
      ? t.id === ref.id
      : ref.line !== undefined &&
        ref.line >= t.line &&
        ref.line < t.line + t.nlines,
  );
  if (!thread?.anchor || !thread.messages.length) {
    throw new Error("That comment thread is no longer in the source.");
  }
  if (thread.overleaf) {
    return;
  }
  // Its highlight where it is in the paragraph, else the paragraph's start
  const { anchor, highlight } = thread;
  let found: { line: number; start: number; end: number } | undefined;
  for (let n = anchor.line; highlight && !found && n <= anchor.end_line; n++) {
    found = findInSource(lines, n, highlight.text);
  }
  toEditor({
    type: "select",
    from: found
      ? { line: found.line, column: found.start }
      : { line: anchor.line, column: 0 },
    to: found
      ? { line: found.line, column: found.end }
      : { line: anchor.line, column: lines[anchor.line - 1]?.length ?? 0 },
  });
  await sleep(300);
  window.dispatchEvent(new Event("add-new-review-comment"));
  // Overleaf's comment box is a small editor of its own, out of sight
  let box: HTMLElement | null = null;
  for (let i = 0; i < 30 && !box; i++) {
    await sleep(100);
    box =
      document
        .querySelector(".review-panel-add-comment-editor")
        ?.shadowRoot?.querySelector<HTMLElement>(".cm-content") ?? null;
  }
  if (!box) {
    throw new Error("Overleaf's comment form didn't open.");
  }
  const [first] = thread.messages;
  // Pasted into that box, since typing commands go to whatever editor the
  // page thinks has focus, which can be the document's
  const data = new DataTransfer();
  data.setData(
    "text/plain",
    first.author === me ? first.text : `${first.author}: ${first.text}`,
  );
  box.focus();
  box.dispatchEvent(
    new ClipboardEvent("paste", {
      clipboardData: data,
      bubbles: true,
      cancelable: true,
    }),
  );
  const root = box.getRootNode() as ShadowRoot;
  const button = root.host
    ?.closest("form")
    ?.querySelector<HTMLButtonElement>('button[type="submit"]');
  for (let i = 0; i < 20 && button?.disabled; i++) {
    await sleep(100);
  }
  if (!button || button.disabled) {
    throw new Error("Couldn't fill in Overleaf's comment form.");
  }
  button.click();
  // Time for Overleaf to save it before it's linked
  await sleep(1500);
}

/** Do what the viewer with comments asks. */
async function onReviewMessage(message: FromReview): Promise<void> {
  const r = review;
  if (!r) {
    return;
  }
  const author = getCommentAuthor();
  const ref = (m: { id?: string; line?: number }) =>
    m.id ? { id: m.id } : { line: m.line };
  try {
    switch (message.type) {
      case "ready":
        r.ready = true;
        r.buildId = null;
        if (r.local) {
          await refreshReviewThreads(true);
        } else {
          await sendOverleafPdf();
        }
        return;
      case "locate": {
        const found = await getSourceAt(
          message.page,
          message.x,
          message.y,
          message.context,
        );
        postToReview({ type: "located", reqId: message.reqId, ...found });
        return;
      }
      case "sourceAt":
      case "openSource": {
        const found =
          message.type === "openSource"
            ? { file: message.file, line: message.line }
            : await getSourceAt(
                message.page,
                message.x,
                message.y,
                message.context,
              );
        if (!found || !(await openDocument(found.file))) {
          postToReview({ type: "status", text: "No source found there." });
          return;
        }
        toEditor({ type: "goto", line: found.line, column: 0 });
        return;
      }
      case "add": {
        const edit = await editSource(message.file, (lines) =>
          getAddEdit(
            lines,
            message.line,
            author,
            message.text,
            message.highlight,
            message.occ,
          ),
        );
        // On Overleaf too, so it's in its review panel, kept in step
        const id = /\bid=([0-9a-f]{8})\b/.exec(edit.insert[0])?.[1];
        if (id) {
          try {
            await postToOverleaf(message.file, { id }, author.name);
          } catch (e) {
            postToReview({
              type: "status",
              text: `Saved in the source, but not on Overleaf: ${
                e instanceof Error ? e.message : e
              }`,
            });
            overleafSyncedFile = null;
            await refreshReviewThreads(false);
            return;
          }
        }
        break;
      }
      case "reply":
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), getReply(author, message.text)),
        );
        break;
      case "resolve":
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), (t) => ({
            ...t,
            resolved: message.resolved,
          })),
        );
        break;
      case "delete": {
        // One kept in step with Overleaf goes there too, first, or the
        // next sync would bring it back
        const thread = getReviewThreads(
          new Map([
            [message.file, reviewSources?.current.get(message.file) ?? ""],
          ]),
        ).find((t) =>
          message.id
            ? t.id === message.id
            : message.line !== undefined &&
              message.line >= t.line &&
              message.line < t.line + t.nlines,
        );
        const docId = getDocIds().get(message.file);
        if (thread?.overleaf && currentProjectId) {
          if (!docId) {
            throw new Error(
              `Open ${message.file} in Overleaf to delete its comment there.`,
            );
          }
          await deleteOverleafThread(currentProjectId, docId, thread.overleaf);
        }
        await editSource(message.file, (lines) =>
          getThreadEdit(lines, ref(message), null),
        );
        break;
      }
      case "goto":
        toEditor({ type: "goto", line: message.line, column: message.column });
        return;
      case "pointer": {
        // Its place on this page, over the viewer
        const frame = r.frame.getBoundingClientRect();
        const point = message.point;
        pdfPointer(
          point && !r.local
            ? {
                page: point.page,
                h: point.x,
                v: point.y,
                clientX: frame.left + point.clientX,
                clientY: frame.top + point.clientY,
              }
            : null,
        );
        return;
      }
      case "postToOverleaf":
        await postToOverleaf(message.file, ref(message), author.name);
        break;
      case "openIssue":
        if (/^https?:\/\//.test(message.url)) {
          window.open(message.url, "_blank", "noopener");
        }
        return;
    }
    postToReview({ type: "status", text: "" });
    // So a change to a thread kept in step with Overleaf goes there now
    overleafSyncedFile = null;
    await refreshReviewThreads(false);
  } catch (e) {
    postToReview({
      type: "status",
      text: e instanceof Error ? e.message : String(e),
    });
  }
}

/** Hear from the viewer with comments, and only from it. */
function watchReview(): void {
  const origin = new URL(chrome.runtime.getURL("")).origin;
  window.addEventListener("message", (event) => {
    if (
      !review ||
      event.source !== review.frame.contentWindow ||
      event.origin !== origin ||
      event.data?.calkit !== "review"
    ) {
      return;
    }
    void onReviewMessage(event.data as FromReview);
  });
}

/**
 * A button in Overleaf's PDF toolbar that shows the PDF with the comments
 * in its source, remembered per Overleaf project. Mounted again whenever
 * Overleaf redraws the toolbar.
 */
function mountCommentsToggle(): void {
  const toolbar = document.querySelector<HTMLElement>(".toolbar-pdf-left");
  const existing = document.getElementById("calkit-comments-toggle");
  const projectId = currentProjectId;
  // This computer's PDF always has them, so it's only for Overleaf's
  if (!toolbar || !projectId || !isExtensionAlive() || localPdf) {
    existing?.remove();
    return;
  }
  // Redrawn by Overleaf, so shown again where it now is
  if (commentsOn && !review?.host.isConnected) {
    review = null;
    showOverleafReview();
  }
  if (
    existing?.parentElement === toolbar &&
    existing.dataset.on === `${commentsOn}` &&
    existing.dataset.project === projectId
  ) {
    return;
  }
  const first = !existing || existing.dataset.project !== projectId;
  existing?.remove();
  const set = (on: boolean) => {
    commentsOn = on;
    void chrome.storage.local.get(COMMENTS_KEY).then((stored) => {
      const all: Record<string, boolean> = stored[COMMENTS_KEY] ?? {};
      all[projectId] = on;
      void chrome.storage.local.set({ [COMMENTS_KEY]: all });
    });
    if (on) {
      showOverleafReview();
    } else {
      hideOverleafReview();
    }
    mountCommentsToggle();
  };
  const button = el("button", {
    text: "Comments",
    title: commentsOn
      ? "Hide the comments in the source"
      : "Show the PDF with the comments in its source, and add some",
    attrs: {
      id: "calkit-comments-toggle",
      "aria-pressed": String(commentsOn),
    },
    style: {
      marginLeft: "8px",
      border: "none",
      padding: "2px 10px",
      borderRadius: "999px",
      cursor: "pointer",
      font: "inherit",
      fontSize: "12px",
      whiteSpace: "nowrap",
      background: commentsOn ? "#009688" : "rgba(127, 127, 127, 0.18)",
      color: commentsOn ? "#fff" : "inherit",
    },
    onClick: () => set(!commentsOn),
  });
  button.dataset.on = `${commentsOn}`;
  button.dataset.project = projectId;
  toolbar.append(button);
  // The last choice for this project applies when it's opened
  if (first) {
    void chrome.storage.local.get(COMMENTS_KEY).then((stored) => {
      if ((stored[COMMENTS_KEY] ?? {})[projectId] && !commentsOn) {
        set(true);
      }
    });
  }
}

/** The pane Overleaf shows its PDF in, around pdf.js's pages. */
function getPdfPane(): HTMLElement | null {
  const viewer = document.querySelector<HTMLElement>(".pdfViewer");
  return (
    viewer?.closest<HTMLElement>(".pdf-viewer, .pdfjs-viewer, .pdf") ??
    viewer?.parentElement ??
    null
  );
}

/** Keep the PDF switch in the toolbar as Overleaf redraws it. */
function watchPdfSwitch(): void {
  let timer: ReturnType<typeof setTimeout> | undefined;
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      mountPdfSwitch();
      mountCommentsToggle();
    }, 200);
  }).observe(document.body, { childList: true, subtree: true });
}

/** Which PDF someone last chose for an Overleaf project, by its ID. */
const PDF_SOURCE_KEY = "pdfSources";

/**
 * A switch in Overleaf's PDF toolbar between its PDF and the one built on
 * this computer, for a project checked out here, remembered per Overleaf
 * project. Mounted again whenever Overleaf redraws the toolbar.
 */
function mountPdfSwitch(): void {
  const check = lastCheck;
  // Beside Recompile, the logs, and download
  const toolbar = document.querySelector<HTMLElement>(".toolbar-pdf-left");
  const existing = document.getElementById("calkit-pdf-switch");
  if (!check?.link.local_path || !toolbar || !isExtensionAlive()) {
    existing?.remove();
    return;
  }
  // Redrawn by Overleaf, so shown again where it now is
  if (localPdf && !localPdf.host.isConnected) {
    showLocalPdf(localPdf.link, localPdf.path);
    return;
  }
  const local = Boolean(localPdf);
  const edits = check.status.commits_from_overleaf;
  if (
    existing?.parentElement === toolbar &&
    existing.dataset.local === `${local}` &&
    existing.dataset.edits === `${edits}`
  ) {
    return;
  }
  existing?.remove();
  const choose = (useLocal: boolean) => {
    void chrome.storage.local.get(PDF_SOURCE_KEY).then((stored) => {
      const sources: Record<string, string> = stored[PDF_SOURCE_KEY] ?? {};
      sources[check.overleafProjectId] = useLocal ? "local" : "overleaf";
      void chrome.storage.local.set({ [PDF_SOURCE_KEY]: sources });
    });
    if (useLocal) {
      showLocalPdf(check.link, check.status.path);
    } else {
      hideLocalPdf();
    }
  };
  const option = (text: string, useLocal: boolean) =>
    el("button", {
      text,
      title: useLocal
        ? "The PDF the pipeline built on this computer, without waiting " +
          "on Overleaf to compile" +
          (edits
            ? `, without ${edits} edit${
                edits === 1 ? "" : "s"
              } made on Overleaf since the last sync`
            : "")
        : "Overleaf's own PDF",
      style: {
        border: "none",
        padding: "2px 8px",
        borderRadius: "999px",
        cursor: "pointer",
        font: "inherit",
        fontSize: "12px",
        whiteSpace: "nowrap",
        background: useLocal === local ? "#009688" : "transparent",
        color: useLocal === local ? "#fff" : "inherit",
      },
      onClick: () => {
        if (useLocal !== local) {
          choose(useLocal);
        }
      },
    });
  const toggle = el(
    "div",
    {
      attrs: { id: "calkit-pdf-switch", title: "Which PDF to show" },
      style: {
        display: "inline-flex",
        alignItems: "center",
        gap: "2px",
        marginLeft: "8px",
        padding: "2px",
        borderRadius: "999px",
        background: "rgba(127, 127, 127, 0.18)",
      },
    },
    [option("Overleaf", false), option("This computer", true)],
  );
  toggle.dataset.local = `${local}`;
  toggle.dataset.edits = `${edits}`;
  // Before Comments, whichever was put back last
  const comments = document.getElementById("calkit-comments-toggle");
  if (comments?.parentElement === toolbar) {
    toolbar.insertBefore(toggle, comments);
  } else {
    toolbar.append(toggle);
  }
  // The first time it's shown for this project, the last choice applies
  if (!existing) {
    void chrome.storage.local.get(PDF_SOURCE_KEY).then((stored) => {
      const source = (stored[PDF_SOURCE_KEY] ?? {})[check.overleafProjectId];
      if (source === "local" && !localPdf && lastCheck === check) {
        showLocalPdf(check.link, check.status.path);
      }
    });
  }
}

/**
 * Where the panel's answers come from: the checkout on this computer, or
 * the hub, with, from the hub, a way to work on the project without
 * installing anything.
 */
function renderWhere(link: OverleafLinkPublic): HTMLElement {
  if (link.local_path) {
    // Opens it in the editor, which is what the path is there for
    return el("div", { class: "dim small" }, [
      document.createTextNode("On this computer: "),
      renderOpenLocally(linkKey(link), undefined, true, link.local_path),
    ]);
  }
  return el("div", { class: "dim small" }, [
    document.createTextNode(`Via ${new URL(hubWebUrl).host}`),
    ...(link.github_repo_url
      ? [
          document.createTextNode(" \u00b7 "),
          el("a", {
            text: "Open in Codespaces",
            href: `https://codespaces.new${
              new URL(link.github_repo_url).pathname
            }?quickstart=1`,
            title: "Work on the project in a GitHub Codespace",
            attrs: { target: "_blank" },
          }),
        ]
      : []),
  ]);
}

/** Where a run of the pipeline happens, as a sentence would say it. */
function getRunPlace(run: PipelineRun | undefined): string {
  return run?.location === "local" ? "on this computer" : "on GitHub Actions";
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
  const project = `${link.project_owner_name}/${link.project_name}`;
  // Worked on here, so the hub's parts stay out of the way
  const local = Boolean(link.local_path);
  const badge = status.in_sync
    ? el("span", { class: "badge ok", text: "in sync" })
    : el("span", {
        class: figures.length ? "badge danger" : "badge warn",
        text: figures.length
          ? `${figures.length} figure${figures.length === 1 ? "" : "s"} to sync`
          : "out of sync",
      });
  // What a sync would do, set aside while a run or sync makes it out of
  // date, with what's going on said instead
  const details = el("div");
  const busy = el("div");
  body.append(
    el("div", { class: "row" }, [
      el("div", { class: "grow" }, [
        local
          ? el("div", { text: project })
          : el("a", {
              text: project,
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
        renderWhere(link),
      ]),
      badge,
    ]),
  );
  body.append(renderLocalChanges(project, reload, link.local_path));
  body.append(busy, details);
  if (status.in_sync) {
    details.append(
      el("div", {
        class: "dim small",
        style: { paddingTop: "6px" },
        text: local
          ? "Overleaf has everything from this computer."
          : "Everything here matches the Calkit project.",
      }),
    );
  }
  if (figures.length) {
    details.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Figures to sync",
      }),
      ...figures.map(fileRow),
    );
  }
  if (others.length) {
    details.append(
      el("div", {
        class: "small",
        style: { marginTop: "8px", fontWeight: "600" },
        text: "Other files to sync",
      }),
      ...others.map(fileRow),
    );
  }
  if (status.files_to_delete.length) {
    details.append(
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
    details.append(
      el("div", {
        class: "dim small",
        style: { marginTop: "8px" },
        text:
          `${count} Overleaf ${count === 1 ? "change" : "changes"} ` +
          "will come back into the project on the next sync.",
      }),
    );
  }
  // Something stale is what a run would fix
  const stale = [...status.files_to_push, ...status.files_to_delete].some(
    (f) => f.stage_status && f.stage_status.status !== "up-to-date",
  );
  body.append(renderRuns(link, stale));
  const syncButton = el("button", {
    class: "action",
    text: "Sync now",
    disabled: !canWrite(link) || status.in_sync,
    title: canWrite(link)
      ? "Push project files to Overleaf and pull Overleaf edits back"
      : "You need write access to this project to sync",
  });
  const message = el("div", { class: "small" });
  syncButton.addEventListener("click", async () => {
    // Running saves and syncs when it's done, so that's the sync
    if (runFirst.isConnected && runFirst.checked) {
      void startRun(link);
      return;
    }
    loadGeneration++;
    syncButton.disabled = true;
    clear(message).append(loading("Syncing"));
    try {
      const result = await syncOverleaf(
        link.project_owner_name,
        link.project_name,
        status.path,
      );
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
          (result.commits_from_overleaf === 1
            ? " from Overleaf was"
            : "s from Overleaf were") +
          " synced to the main project.",
      };
      reload();
    } catch (e) {
      syncButton.disabled = false;
      clear(message).append(
        errorMessage(e instanceof Error ? e.message : String(e)),
      );
    }
  });
  // Syncing, and on this computer running what's out of date first, or,
  // with nothing to sync, running and syncing after. Redrawn once it's
  // known what's out of date, which takes a moment.
  const actions = el("div", { class: "actions" });
  const openLocally = local
    ? renderOpenLocally(project, undefined, true)
    : null;
  const refresh = el("button", {
    class: "action secondary",
    text: "Refresh",
    onClick: reload,
  });
  const runFirst = el("input", { type: "checkbox" }) as HTMLInputElement;
  runFirst.addEventListener("change", () => {
    runBeforeSync = runFirst.checked;
    void chrome.storage.local.set({ [RUN_BEFORE_SYNC_KEY]: runBeforeSync });
  });
  const drawActions = () => {
    const pipeline =
      local && railPipeline?.key === linkKey(link)
        ? railPipeline.pipeline
        : undefined;
    const staleStages = (pipeline?.ck_stages ?? []).filter((name) =>
      ["stale", "not-run"].includes(
        pipeline?.stage_statuses[name]?.status ?? "",
      ),
    );
    const running = Boolean(activeRun()) || Boolean(starting?.busy);
    runFirst.checked = runBeforeSync;
    const stagesText = `Out of date: ${staleStages.join(", ")}`;
    clear(actions).append(
      ...[
        status.in_sync ? null : syncButton,
        !status.in_sync && staleStages.length
          ? el("label", { class: "check", title: stagesText }, [
              runFirst,
              document.createTextNode("Run the pipeline first"),
            ])
          : null,
        status.in_sync && staleStages.length
          ? el("button", {
              class: "action",
              text: "Run and sync",
              title: `Run the pipeline on this computer, then save and sync. ${stagesText}`,
              disabled: !canWrite(link) || running,
              onClick: () => void startRun(link),
            })
          : null,
        // Its button in this row, and anything it says below it
        openLocally,
        refresh,
      ].filter((node): node is HTMLElement => Boolean(node)),
    );
    syncButton.disabled = !canWrite(link) || status.in_sync || running;
    syncButton.title = staleStages.length
      ? `Push project files to Overleaf and pull Overleaf edits back. ${stagesText}`
      : syncButton.title;
  };
  drawPanelActions = () => {
    if (actions.isConnected) {
      drawActions();
    }
  };
  drawActions();
  if (local) {
    void refreshRailPipeline(link);
  }
  body.append(actions, message);
  statusParts.add({ link, hide: [badge, details, actions], busy });
  drawStatusParts();
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
        clear(repoResults);
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
    // Filled in as the hub answers, without holding up the rest, which
    // for a project on this computer doesn't need the hub at all
    const pickers = el("div", {
      class: "muted-box stack",
      style: { marginBottom: "8px" },
    });
    void Promise.all([
      renderHubPicker(reload),
      renderProjectPicker({
        activeProject: settings.activeProject,
        onChange: reload,
      }),
    ]).then((parts) => pickers.append(...parts));
    const cached =
      lastCheck?.overleafProjectId === overleafProjectId &&
      lastCheck.hubWebUrl === hubWebUrl
        ? lastCheck
        : null;
    const content = el("div");
    // The hub's pickers are beside the point for a project worked on here
    clear(body).append(...(cached?.link.local_path ? [] : [pickers]), content);
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
    if (link.local_path) {
      pickers.remove();
    } else if (!pickers.isConnected) {
      body.prepend(pickers);
    }
    if (!cached) {
      clear(content).append(
        loading(`Checking ${link.project_owner_name}/${link.project_name}`),
      );
    }
    const statusRequest = {
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
    } as const;
    // On this computer, what's known from the last pull comes at once,
    // and is shown while Overleaf is asked for anything newer
    if (link.local_path) {
      const known = await send({ ...statusRequest, pull: false }).catch(
        () => [],
      );
      if (!current()) {
        return;
      }
      if (known.length && !known[0].pulled) {
        // As of the last sync, e.g., by a run that just ended
        checkingAfterSync = false;
        renderStatus(content, link, known[0], reload);
        content.append(loading("Checking Overleaf for new edits"));
      }
    }
    const files = link.local_path
      ? await getOverleafFiles(overleafProjectId)
      : null;
    const statuses = await send({
      ...statusRequest,
      overleafFiles: files?.shas,
      overleafTexts: files?.texts,
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
    currentLink = link;
    void checkCitations();
    lastCheck = { overleafProjectId, hubWebUrl, link, status: statuses[0] };
    // Checked since the last run or sync, so it's current again
    checkingAfterSync = false;
    renderStatus(content, link, statuses[0], reload);
    showNotice();
    content.append(renderInsert(link, statuses[0].path, reload));
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
    checkingAfterSync = false;
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
type LauncherTone =
  | "idle"
  | "attention"
  | "reconnect"
  | "unlinked"
  | "running"
  | "syncing";

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
      running: "Calkit: running",
      syncing: "Calkit: syncing",
    }[tone],
    class: ["idle", "running", "syncing"].includes(tone) ? "" : "attention",
  });
  button.addEventListener("click", onClick);
  root.append(style, button);
  document.body.append(host);
}

// Remembered so a closed panel can still show that something is waiting
let lastSyncNeeded = false;
// A sync from here is going, which the sidebar and launcher show
let syncing = false;
let lastTokenProblem = false;
let lastUnlinked = false;

function launcherTone(): LauncherTone {
  if (lastTokenProblem) {
    return "reconnect";
  }
  if (lastUnlinked) {
    return "unlinked";
  }
  if (syncing) {
    return "syncing";
  }
  if (activeRun()) {
    return "running";
  }
  return lastSyncNeeded ? "attention" : "idle";
}

function openPanel(
  overleafProjectId: string,
  fill?: (body: HTMLElement) => void,
): void {
  document.getElementById(LAUNCHER_ID)?.remove();
  panel = mountPanel({
    id: PANEL_ID,
    title: "Calkit",
    onClose: () => {
      panel = null;
      mountLauncher(() => openPanel(overleafProjectId), launcherTone());
    },
  });
  if (fill) {
    fill(panel.body);
  } else {
    void load(overleafProjectId);
  }
}

/** Open the panel on something to do, e.g., a fix from a tooltip. */
function showInPanel(fill: (body: HTMLElement) => void): void {
  const overleafProjectId = currentProjectId;
  if (!overleafProjectId) {
    return;
  }
  openPanel(overleafProjectId, (body) => {
    // Its own element, so what clears it keeps the way back
    const content = el("div");
    body.append(
      el("button", {
        class: "action secondary",
        text: "\u2190 Back",
        onClick: () => openPanel(overleafProjectId),
      }),
      content,
    );
    fill(content);
  });
}

function teardown(): void {
  tokenWatcher?.disconnect();
  tokenWatcher = null;
  document.getElementById(TOKEN_PANEL_ID)?.remove();
  document.getElementById(LAUNCHER_ID)?.remove();
  panel?.remove();
  panel = null;
  currentProjectId = null;
  currentLink = null;
}

function sync(): void {
  if (new URL(window.location.href).pathname.startsWith("/user/settings")) {
    void watchForNewToken();
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
    // Cards link to the hub the project was found on, and can show before
    // the panel, which also sets it, is opened
    hubWebUrl = hub;
    currentLink = link;
    void checkCitations();
    drawRail();
    if (railOpen && railPipeline?.key !== linkKey(link)) {
      void refreshRailPipeline(link);
    }
    if (pipelineRuns?.key !== linkKey(link)) {
      void refreshRuns(link);
    }
    const files = link.local_path
      ? await getOverleafFiles(overleafProjectId)
      : null;
    const statuses = await send({
      type: "overleaf.status",
      owner: link.project_owner_name,
      project: link.project_name,
      overleafProjectId,
      path: link.path,
      overleafFiles: files?.shas,
      overleafTexts: files?.texts,
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
    checkingAfterSync = false;
    drawStatusParts();
    drawRail();
    mountPdfSwitch();
    // Nothing to say if the panel was opened in the meantime, or if the
    // page moved on to another project
    if (panel || currentProjectId !== overleafProjectId) {
      return;
    }
    mountLauncher(() => openPanel(overleafProjectId), launcherTone());
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
let recheckTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * Check again what there is to sync, a while after the last change, e.g.,
 * a save, or an edit Overleaf saves by itself, like a comment added from
 * the PDF, which the sync has to bring to this computer.
 */
function recheckAfterEdit(delay: number): void {
  clearTimeout(recheckTimer);
  recheckTimer = setTimeout(() => {
    if (!currentProjectId) {
      return;
    }
    // The button has to notice it too, not just an already-open panel
    if (panel) {
      void load(currentProjectId);
    } else {
      void checkSyncStatus(currentProjectId);
    }
  }, delay);
}

function watchForSaves(): void {
  document.addEventListener(
    "keydown",
    (event) => {
      const isSave =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (isSave && currentProjectId) {
        recheckAfterEdit(2000);
      }
    },
    true,
  );
}

const RAIL_TAB_ID = "calkit-rail-tab";
const RAIL_PANE_ID = "calkit-rail-pane";
// Whether Calkit's tab is the one showing in Overleaf's sidebar
let railOpen = false;
let railPane: { host: HTMLElement; body: HTMLElement } | null = null;
// The component opened in the sidebar, kept through redraws, which come
// with every edit
let railCard: { key: string; element: HTMLElement } | null = null;
// The stage whose details are open in the sidebar
let railStage: string | null = null;
// Redraws the open panel's sync and run buttons, e.g., once it's known
// what's out of date
let drawPanelActions: () => void = () => undefined;

/**
 * A stage's details in the sidebar: why it's out of date, what it runs,
 * reads, and makes, with ways to open it in the editor on this computer
 * or on the hub.
 */
function renderStageCard(
  link: OverleafLinkPublic,
  pipeline: ProjectPipeline,
  name: string,
): HTMLElement {
  const base = projectUrl(
    hubWebUrl,
    link.project_owner_name,
    link.project_name,
  );
  const stage = pipeline.dvc_stages?.[name];
  const status = pipeline.stage_statuses[name];
  const cmd = [stage?.cmd ?? ""].flat().join(" ");
  // Environment locks and the like are inputs, but not anyone's concern
  const deps = (stage?.deps ?? []).filter(
    (d) => !d.startsWith(".calkit/") && !/(^|\/)(uv|pixi)\.lock$/.test(d),
  );
  // A manual step names its file in what it says to do, not to run it
  const manual = /calkit manual-step --message '((?:[^']|'\\'')*)'/.exec(cmd);
  const source = manual ? undefined : deps.find((d) => cmd.includes(d));
  const outs = (stage?.outs ?? []).map((o) =>
    typeof o === "string" ? o : Object.keys(o)[0],
  );
  const list = (label: string, paths: string[]) =>
    paths.length
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: `${label} ` }),
          document.createTextNode(
            paths.length > 4
              ? `${paths.slice(0, 4).join(", ")}, and ${paths.length - 4} more`
              : paths.join(", "),
          ),
        ])
      : null;
  const changed = [
    ...(status?.modified_command ? ["its command"] : []),
    ...(status?.modified_inputs ?? []),
  ];
  const project = `${link.project_owner_name}/${link.project_name}`;
  return el("div", { class: "card" }, [
    changed.length
      ? el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text: `Changed since it last ran: ${changed.join(", ")}`,
        })
      : status?.missing_outputs.length
      ? el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text: `Missing: ${status.missing_outputs.join(", ")}`,
        })
      : null,
    manual
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: "Manual step: " }),
          document.createTextNode(manual[1].replace(/'\\''/g, "'")),
        ])
      : null,
    source
      ? el("div", { class: "small" }, [
          el("span", { class: "dim", text: "Runs " }),
          document.createTextNode(source),
        ])
      : null,
    list(
      "Reads",
      deps.filter((d) => d !== source),
    ),
    list("Makes", outs),
    el("div", { class: "actions", style: { alignItems: "center" } }, [
      link.local_path ? renderOpenLocally(project, source, true) : null,
      el("a", {
        class: "small",
        text: "Open in Calkit",
        href: `${base}/pipeline?stage=${encodeURIComponent(name)}`,
        attrs: { target: "_blank" },
      }),
    ]),
  ]);
}

let railPipeline: {
  key: string;
  pipeline?: ProjectPipeline;
  error?: string;
} | null = null;

/**
 * A Calkit tab in Overleaf's sidebar, listing what the open document shows
 * from the project and the pipeline's stages, with a button to run it.
 *
 * Overleaf renders only its active tab's pane, so this one is put in the
 * sidebar's content area while it's open, with Overleaf's pane hidden,
 * rather than being a tab Overleaf knows about.
 */
function watchRail(): void {
  const style = document.createElement("style");
  style.textContent = `
    .ide-rail-tab-content.calkit-open > :not(#${RAIL_PANE_ID}) {
      display: none !important;
    }
    #${RAIL_PANE_ID} { height: 100%; overflow-y: auto; }
    body.calkit-rail-open .ide-rail-tab-link.active:not(#${RAIL_TAB_ID}) {
      background-color: transparent !important;
      color: inherit !important;
    }
    body.calkit-rail-open
      .ide-rail-tab-link.active:not(#${RAIL_TAB_ID})::after {
      display: none !important;
    }
    #${RAIL_TAB_ID} svg {
      width: 20px;
      height: 20px;
      display: block;
      margin: 0 auto;
      color: #009688;
    }
    #${RAIL_TAB_ID}.active svg { color: #fff; }
    #${RAIL_TAB_ID} { position: relative; }
    #${RAIL_TAB_ID} .calkit-rail-dot {
      position: absolute; bottom: 4px; right: 6px; width: 8px; height: 8px;
      border-radius: 50%; background: #e5484d;
      box-shadow: 0 0 0 2px var(--bg-primary-themed, #fff);
    }
  `;
  document.head.append(style);
  // One of Overleaf's own tabs brings its pane back. The one it thinks is
  // showing would otherwise close the sidebar instead.
  document.addEventListener(
    "click",
    (event) => {
      const target = (event.target as Element | null)?.closest?.(
        ".ide-rail-tab-link",
      );
      if (!railOpen || !target || target.id === RAIL_TAB_ID) {
        return;
      }
      if (target.classList.contains("active")) {
        event.preventDefault();
        event.stopPropagation();
      }
      setRail(false);
    },
    true,
  );
  let timer: ReturnType<typeof setTimeout> | undefined;
  const ensure = () => {
    const first = document.getElementById("ide-rail-tabs-tab-file-tree");
    const tabs = first?.parentElement;
    if (!tabs || !currentProjectId) {
      return;
    }
    let tab = document.getElementById(RAIL_TAB_ID);
    if (!tab) {
      tab = el("button", {
        class: "ide-rail-tab-link nav-link",
        attrs: {
          id: RAIL_TAB_ID,
          type: "button",
          role: "tab",
          title: "Calkit",
          "aria-label": "Calkit",
        },
      });
      // Inline, so it takes the tab's color: white while ours is open
      tab.innerHTML = calkitLogo;
      tab.addEventListener("click", () => setRail(!railOpen));
      const separated = tabs.querySelector(".separated-rail-tab");
      if (separated) {
        separated.before(tab);
      } else {
        tabs.append(tab);
      }
    }
    markRailTab();
    // Overleaf underlines the tab whose pane is open by open-rail
    tab.classList.toggle("active", railOpen);
    tab.classList.toggle("open-rail", railOpen);
    tab.setAttribute("aria-selected", String(railOpen));
    if (railOpen) {
      placeRailPane();
    }
  };
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(ensure, 100);
  }).observe(document.body, { childList: true, subtree: true });
}

/**
 * What the open document's components are made from that has no origin
 * defined, with a component made from each and what they all show.
 */
function getOriginGaps(): Map<string, { citation: Citation; uses: string[] }> {
  const gaps = new Map<string, { citation: Citation; uses: string[] }>();
  const items = editorCitations?.items ?? [];
  if (editorProblems?.version !== editorCitations?.version) {
    return gaps;
  }
  editorProblems?.found.forEach((problems, index) => {
    const citation = items[index]?.citation;
    for (const problem of problems) {
      if (problem.kind !== "origin" || !citation) {
        continue;
      }
      const gap = gaps.get(problem.path) ?? { citation, uses: [] };
      const use = citation.key
        ? `${citation.path} \u00b7 ${citation.key}`
        : citation.path;
      if (!gap.uses.includes(use)) {
        gap.uses.push(use);
      }
      gaps.set(problem.path, gap);
    }
  });
  return gaps;
}

/** A dot on the Calkit tab while something here needs an origin defined. */
function markRailTab(): void {
  const tab = document.getElementById(RAIL_TAB_ID);
  if (!tab) {
    return;
  }
  const n = currentLink ? getOriginGaps().size : 0;
  let dot = tab.querySelector<HTMLElement>(".calkit-rail-dot");
  if (!n) {
    dot?.remove();
    tab.title = "Calkit";
    return;
  }
  if (!dot) {
    dot = el("span", { class: "calkit-rail-dot" });
    tab.append(dot);
  }
  tab.title =
    `Calkit: ${n} file${n === 1 ? "" : "s"} this document is made from ` +
    `need${n === 1 ? "s" : ""} an origin defined`;
}

function setRail(open: boolean): void {
  railOpen = open;
  document.body.classList.toggle("calkit-rail-open", open);
  const tab = document.getElementById(RAIL_TAB_ID);
  tab?.classList.toggle("active", open);
  tab?.classList.toggle("open-rail", open);
  tab?.setAttribute("aria-selected", String(open));
  if (!open) {
    document
      .querySelector(".ide-rail-tab-content")
      ?.classList.remove("calkit-open");
    railPane?.host.remove();
    return;
  }
  // A closed sidebar has no content area to show it in, so open it on the
  // file tree first
  const content = document.querySelector(".ide-rail-tab-content");
  if (!content || content.getBoundingClientRect().width < 20) {
    // Its pane is put there once it's drawn, as Overleaf redraws
    document.getElementById("ide-rail-tabs-tab-file-tree")?.click();
  } else {
    placeRailPane();
  }
  drawRail();
  if (currentLink) {
    void refreshRailPipeline(currentLink);
  }
}

// The Calkit pane in Overleaf's sidebar, which brings its own background,
// since its colors follow the system's theme rather than Overleaf's
const RAIL_STYLES = `
  .rail {
    padding: 10px 12px; min-height: 100%; box-sizing: border-box;
    color: var(--ck-fg); background: var(--ck-bg);
  }
  .rail .project {
    flex-direction: column; align-items: flex-start; gap: 2px;
    overflow-wrap: anywhere;
  }
  .rail h3 {
    font-size: 12px; font-weight: 600; margin: 14px 0 4px;
    text-transform: uppercase; letter-spacing: 0.04em;
    color: var(--ck-dim);
  }
  .item {
    display: flex; align-items: center; gap: 6px; width: 100%;
    padding: 3px 4px; border: 0; border-radius: 4px; text-align: left;
    background: none; color: inherit; cursor: pointer;
  }
  .item:hover { background: var(--ck-subtle-bg); }
  .item .grow { min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex: none;
    background: var(--ck-success); }
  .dot.warning { background: var(--ck-warning); }
  .dot.error { background: var(--ck-danger); }
  .dot.unknown { background: var(--ck-dim); }
  /* A row that expands, colored for its state, pointing down when open */
  .twistie { width: 0; height: 0; flex: none; margin: 0 1px 0 2px;
    border-top: 4px solid transparent; border-bottom: 4px solid transparent;
    border-left: 6px solid var(--ck-success);
    transition: transform 0.1s; }
  .twistie.open { transform: rotate(90deg); }
  .twistie.warning { border-left-color: var(--ck-warning); }
  .twistie.error { border-left-color: var(--ck-danger); }
  .twistie.unknown { border-left-color: var(--ck-dim); }
  .item .spinner { width: 8px; height: 8px; border-width: 1.5px;
    flex: none; }
  .card {
    margin: 2px 0 8px 14px; padding: 6px 8px; font-size: 12px;
    border-left: 2px solid var(--ck-border);
  }
  .card > * + * { margin-top: 3px; }
  .card button.action { padding: 1px 6px; font-size: 11px; }
`;

/** Put the pane in the sidebar, where Overleaf may have redrawn it away. */
function placeRailPane(): void {
  const content = document.querySelector(".ide-rail-tab-content");
  if (!content) {
    return;
  }
  if (!railPane) {
    const host = el("div", { attrs: { id: RAIL_PANE_ID } });
    const root = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = STYLES + RAIL_STYLES;
    const body = el("div", { class: "rail" });
    root.append(style, body);
    railPane = { host, body };
    drawRail();
  }
  if (railPane.host.parentElement !== content) {
    content.append(railPane.host);
  }
  content.classList.add("calkit-open");
}

/** Ask the hub for the pipeline's stages, then show them. */
async function refreshRailPipeline(link: OverleafLinkPublic): Promise<void> {
  try {
    const pipeline = await send({
      type: "project.pipeline",
      owner: link.project_owner_name,
      project: link.project_name,
    });
    railPipeline = { key: linkKey(link), pipeline };
    drawPanelActions();
  } catch (e) {
    railPipeline = {
      key: linkKey(link),
      error: e instanceof Error ? e.message : String(e),
    };
  }
  drawRail();
}

function drawRail(): void {
  // One of the pipeline's runs, opening its log, or GitHub's page for it
  const renderRunItem = (link: OverleafLinkPublic, run: PipelineRun) => {
    const when = new Date(run.started ?? run.created).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
    const active = ["queued", "running"].includes(run.status);
    const parts = [
      active
        ? el("span", { class: "spinner" })
        : el("span", {
            class: `dot ${
              run.status === "succeeded"
                ? ""
                : run.status === "failed"
                ? "error"
                : "unknown"
            }`,
          }),
      // All here, or all on GitHub, as the panel says above
      el("span", { class: "grow small", text: when }),
      el("span", { class: "dim small", text: run.status }),
    ];
    if (run.location === "local") {
      return el(
        "button",
        {
          class: "item",
          title: run.error ?? "Show its log",
          onClick: () => openRunLog(link, run),
        },
        parts,
      );
    }
    return run.url
      ? el(
          "a",
          { class: "item", href: run.url, attrs: { target: "_blank" } },
          parts,
        )
      : el("div", { class: "item" }, parts);
  };
  if (!railPane) {
    return;
  }
  const body = clear(railPane.body);
  const link = currentLink;
  if (!link) {
    body.append(
      el("div", {
        class: "small",
        text: "This paper isn't linked to a Calkit project yet.",
      }),
      el("div", { class: "actions" }, [
        el("button", {
          class: "action",
          text: "Link it",
          onClick: () => currentProjectId && openPanel(currentProjectId),
        }),
      ]),
    );
    return;
  }
  const base = projectUrl(
    hubWebUrl,
    link.project_owner_name,
    link.project_name,
  );
  body.append(
    el("div", { class: "row project" }, [
      el("a", {
        text: linkKey(link),
        href: base,
        attrs: { target: "_blank" },
      }),
      renderWhere(link),
    ]),
  );
  // What's going on between the paper and its project
  const running = activeRun();
  const status =
    lastCheck && linkKey(lastCheck.link) === linkKey(link)
      ? lastCheck.status
      : null;
  if (syncing) {
    body.append(loading("Syncing with the project"));
  } else if (running) {
    body.append(
      loading(
        running.location === "local"
          ? getRunActivity(running)
          : running.status === "running"
          ? `Running ${getRunPlace(running)}`
          : `Waiting to run ${getRunPlace(running)}`,
      ),
    );
  } else if (status?.in_sync) {
    body.append(
      el("div", { class: "row small" }, [
        el("span", { class: "dot" }),
        el("span", { text: "In sync with the project" }),
      ]),
    );
  } else if (status) {
    const { button, message } = syncNow(link, status.path, true);
    body.append(
      el("div", { class: "row small" }, [
        el("span", { class: "dot warning" }),
        el("span", { class: "grow", text: "Changes to sync" }),
        button,
      ]),
      message,
    );
  }
  // Upstream of the components, so not in their list, but where Calkit
  // can't tell where something came from
  const gaps = getOriginGaps();
  if (gaps.size) {
    body.append(
      el("h3", {
        text: "Origin needed",
        attrs: { id: "calkit-origin-needed" },
      }),
      el("div", {
        class: "dim small",
        text:
          "Calkit can't tell where these came from. Components here are " +
          "made from them.",
      }),
    );
    for (const [path, gap] of gaps) {
      body.append(
        el("div", { class: "card" }, [
          el("div", { class: "row small" }, [
            el("span", { class: "dot error" }),
            el("span", { class: "grow", text: path }),
          ]),
          el("div", {
            class: "dim small",
            text: `Used by ${gap.uses.join(", ")}`,
          }),
          link.current_user_access === "read"
            ? null
            : renderDefineOrigin(link, gap.citation, path),
        ]),
      );
    }
  }
  // Components the open document shows, each with what's wrong with it
  body.append(el("h3", { text: "Components" }));
  const items = editorCitations?.items ?? [];
  const checked =
    editorProblems && editorProblems.version === editorCitations?.version
      ? editorProblems.found
      : null;
  if (!items.length) {
    body.append(
      el("div", {
        class: "dim small",
        text: "Nothing from the project here yet.",
      }),
    );
  }
  const seen = new Map<string, number>();
  items.forEach((item, index) => {
    const problems = checked?.[index];
    // What it shows, and which time, since its line moves with edits
    const text = citationText(item.citation);
    const nth = (seen.get(text) ?? 0) + 1;
    seen.set(text, nth);
    const key = `${text}#${nth}`;
    const label = item.citation.key
      ? `${item.citation.path} · ${item.citation.key}`
      : item.citation.path;
    body.append(
      el(
        "button",
        {
          class: "item",
          title: problems?.length
            ? problems.map((p) => p.message).join("\n")
            : `Line ${item.line}`,
          attrs: { "aria-expanded": String(railCard?.key === key) },
          onClick: () => {
            toEditor({ type: "goto", line: item.line, column: item.column });
            if (railCard?.key === key) {
              railCard = null;
            } else {
              const element = el("div", { class: "card" });
              railCard = { key, element };
              void fillCard(element, link, item);
            }
            drawRail();
          },
        },
        [
          el("span", {
            class: `twistie ${
              problems === undefined
                ? "unknown"
                : problems.some((p) => p.severity === "error")
                ? "error"
                : problems.length
                ? "warning"
                : ""
            }${railCard?.key === key ? " open" : ""}`,
          }),
          el("span", { class: "grow small", text: label }),
          el("span", { class: "dim small", text: `${item.line}` }),
        ],
      ),
    );
    if (railCard?.key === key) {
      body.append(railCard.element);
    }
  });
  // The pipeline's stages, and running it
  body.append(el("h3", { text: "Pipeline" }));
  const known = railPipeline?.key === linkKey(link) ? railPipeline : null;
  const pipeline = known?.pipeline;
  if (known?.error) {
    body.append(errorMessage(known.error));
  } else if (!pipeline) {
    body.append(loading());
  } else if (!pipeline.ck_stages.length) {
    body.append(el("div", { class: "dim small", text: "No stages yet." }));
  }
  for (const name of pipeline?.ck_stages ?? []) {
    const status = pipeline?.stage_statuses[name]?.status ?? "unknown";
    const due = ["stale", "not-run"].includes(status);
    // What a run going now will run
    const toRun = Boolean(running) && due;
    body.append(
      el(
        "button",
        {
          class: "item",
          title: status,
          attrs: { "aria-expanded": String(railStage === name) },
          onClick: () => {
            railStage = railStage === name ? null : name;
            drawRail();
          },
        },
        [
          toRun
            ? el("span", { class: "spinner" })
            : el("span", {
                class: `twistie ${
                  status === "up-to-date" ? "" : due ? "warning" : "unknown"
                }${railStage === name ? " open" : ""}`,
              }),
          el("span", { class: "grow small", text: name }),
          status !== "up-to-date"
            ? el("span", {
                class: "dim small",
                text: toRun ? "running" : status,
              })
            : null,
        ],
      ),
    );
    if (railStage === name && pipeline) {
      body.append(renderStageCard(link, pipeline, name));
    }
  }
  body.append(renderRuns(link, true));
  // On this computer, a run is offered only when something's out of date
  const staleStages = (pipeline?.ck_stages ?? []).filter((name) =>
    ["stale", "not-run"].includes(pipeline?.stage_statuses[name]?.status ?? ""),
  );
  if (link.local_path && staleStages.length && !running) {
    body.append(
      el("div", { class: "actions" }, [
        el("button", {
          class: "action",
          text: "Run and sync",
          title:
            "Run the pipeline on this computer, then save and sync. " +
            `Out of date: ${staleStages.join(", ")}`,
          disabled: !canWrite(link) || Boolean(starting?.busy),
          onClick: () => void startRun(link),
        }),
      ]),
    );
  }
  // The latest runs, each with its log
  const runs =
    pipelineRuns?.key === linkKey(link) ? pipelineRuns.runs.runs : [];
  if (runs.length) {
    body.append(el("h3", { text: "Runs" }));
    for (const run of runs.slice(0, 5)) {
      body.append(renderRunItem(link, run));
    }
  }
}

/**
 * List Calkit among Overleaf's own integrations, beside GitHub and
 * Dropbox, as another way to open the panel.
 */
function watchIntegrations(): void {
  // An image has no text color to inherit, so the logo gets its own
  const icon = `data:image/svg+xml,${encodeURIComponent(
    calkitLogo.replace(/currentColor/g, "#009688"),
  )}`;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const addCard = () => {
    const list = document.querySelector(".integrations-panel");
    if (!list || !currentProjectId) {
      return;
    }
    const description = currentLink
      ? `Synced with ${currentLink.project_owner_name}/${currentLink.project_name}.`
      : "Make this paper reproducible.";
    const existing = list.querySelector<HTMLElement>("#calkit-integration");
    if (existing) {
      const text = existing.querySelector(
        ".integrations-panel-card-description",
      );
      if (text && text.textContent !== description) {
        text.textContent = description;
      }
      return;
    }
    const card = el(
      "button",
      {
        class: "integrations-panel-card-button",
        attrs: { id: "calkit-integration", type: "button" },
      },
      [
        el("div", { class: "integrations-panel-card-contents" }, [
          el("div", { class: "integrations-panel-card-icon" }, [
            el("img", {
              attrs: { src: icon, alt: "", width: "32", height: "32" },
            }),
          ]),
          el("div", { class: "integrations-panel-card-inner" }, [
            el("div", { class: "integrations-panel-card-header" }, [
              el("div", {
                class: "integrations-panel-card-title",
                text: "Calkit",
                attrs: { translate: "no" },
              }),
            ]),
            el("p", {
              class: "integrations-panel-card-description",
              text: description,
            }),
          ]),
        ]),
      ],
    );
    card.addEventListener("click", () => {
      if (currentProjectId && !panel) {
        openPanel(currentProjectId);
      }
    });
    // First after the header, being the one that brings the rest together
    const header = list.querySelector(".rail-panel-header");
    if (header) {
      header.after(card);
    } else {
      list.prepend(card);
    }
  };
  new MutationObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(addCard, 100);
  }).observe(document.body, { childList: true, subtree: true });
}

/**
 * Add inserting from the project to the editor's right-click menu, which
 * Overleaf draws itself rather than leaving to the browser. Right-clicking
 * moves the cursor there, so that's where it's inserted.
 */
function watchContextMenu(): void {
  const addItem = () => {
    const menu = document.querySelector<HTMLElement>(
      ".editor-context-menu-container ul[role=menu]",
    );
    const check = lastCheck;
    const ours = menu?.querySelector("#calkit-insert")?.parentElement;
    if (ours) {
      // Kept last, since Overleaf adds some of its own items after opening
      if (ours !== menu?.lastElementChild) {
        menu?.append(menu.querySelector("#calkit-insert-divider") ?? "", ours);
      }
      return;
    }
    if (
      !menu ||
      !check ||
      check.link !== currentLink ||
      check.link.current_user_access === "read"
    ) {
      return;
    }
    const item = el("button", {
      class: "dropdown-item",
      text: "Insert from Calkit\u2026",
      attrs: { id: "calkit-insert", role: "menuitem", type: "button" },
    });
    item.addEventListener("click", () => {
      // Closes Overleaf's menu, as choosing one of its own items would
      menu.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
      showInPanel((body) =>
        body.append(
          renderInsert(check.link, check.status.path, () =>
            openPanel(check.overleafProjectId),
          ),
        ),
      );
    });
    menu.append(
      el("li", {
        class: "dropdown-divider",
        attrs: { id: "calkit-insert-divider", role: "separator" },
      }),
      el("li", { attrs: { role: "none" } }, [item]),
    );
  };
  new MutationObserver(addItem).observe(document.body, {
    childList: true,
    subtree: true,
  });
}

watchForSaves();
watchEditor();
watchPdf();
watchIntegrations();
watchRail();
watchContextMenu();
watchPdfSwitch();
watchReview();
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
    currentLink = null;
    provenanceCache.clear();
    lastCheck = null;
    if (panel) {
      void load(overleafProjectId);
    } else {
      mountLauncher(() => openPanel(overleafProjectId));
      void checkSyncStatus(overleafProjectId);
    }
  },
});
