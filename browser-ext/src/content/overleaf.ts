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
  type Citation,
  type CitationProblem,
  canBeCreatedByPerson,
  citationProblems,
  citationText,
  citationCandidates,
} from "../core/latex";
import { runContentScript } from "../core/lifecycle";
import {
  isUnsupportedByHub,
  type Request,
  RequestFailed,
  send,
} from "../core/messages";
import type {
  GithubRepo,
  OverleafLinkPublic,
  Provenance,
  StageFromScript,
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
  STYLES,
  textInput,
} from "../core/ui";
import type { EditorCitation, FromEditor, ToEditor } from "./overleaf-editor";

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
    try {
      request = upload
        ? {
            // An upload goes where it's named, or with others of its kind
            scriptPath: typed || `${kind}s/${upload.name}`,
            content: await fileBase64(upload),
          }
        : { scriptPath: typed };
      const detected = await send({
        type: "project.stageFromScript",
        owner,
        project,
        ...request,
        shows,
      });
      clear(message);
      renderReview(detected);
    } catch (e) {
      fail(e);
    } finally {
      read.disabled = false;
    }
  });
  const renderReview = (detected: StageFromScript) => {
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
    const copyNote = el("div", { class: "dim small" });
    const chosen = () => choices.find((c) => c.radio.checked)?.output;
    const updateNote = () => {
      const output = chosen();
      copyNote.textContent =
        output && output !== shows
          ? `The pipeline will copy it to ${shows}, where the paper has it.`
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
        copyNote,
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
      clear(message).append(loading("Saving"));
      try {
        const saved = await send({
          type: "project.stageFromScript",
          owner,
          project,
          ...request,
          shows,
          produces: chosen(),
          save: true,
        });
        await showDefined(container, link, citation);
        container.append(renderRunIt(saved, `${owner}/${project}`));
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
      await send({
        type: "project.manualExport",
        owner,
        project,
        path: target,
        sourcePath,
        content: upload ? await fileBase64(upload) : undefined,
        app: appName.value.trim() || undefined,
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
function renderRunIt(saved: StageFromScript, spec: string): HTMLElement {
  const folder = saved.git_repo_url
    .replace(/\.git$/, "")
    .split("/")
    .pop();
  const commands = [
    "curl -LsSf install.calkit.org | sh",
    `calkit clone ${spec}`,
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
        `Added stage ${saved.stage_name}. It hasn't run yet. To run it ` +
        "and bring the result into this paper, on your computer:",
    }),
    el("pre", {
      class: "name",
      style: { whiteSpace: "pre-wrap", margin: "6px 0" },
      text: commands,
    }),
    el("div", { class: "actions" }, [copy]),
  ]);
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
            if (p.source) {
              lines.push(
                el("div", { class: "dim" }, [
                  document.createTextNode(
                    p.stage_kind === "manual-step"
                      ? "Exported manually from "
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
  // A file is named as the project has it, not as written
  const path = citation.kind === "value" ? citation.path : provenance.path;
  const label = citation.key ? `${path}: ${citation.key}` : path;
  container.append(el("div", { class: "name", text: label }));
  const problems = citationProblems(citation, provenance);
  for (const problem of problems) {
    container.append(problemLine(problem));
    if (problem.kind === "origin" && link.current_user_access !== "read") {
      container.append(renderDefineOrigin(link, citation, problem.path));
    }
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
        style: { fontSize: "18px", fontWeight: "600", margin: "4px 0" },
        text: valueText(provenance.value),
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
            href: `${base}/pipeline?stage=${encodeURIComponent(
              provenance.stage,
            )}`,
            attrs: { target: "_blank" },
          }),
          provenance.stage_kind
            ? el("span", {
                class: "dim",
                text: ` \u00b7 ${provenance.stage_kind}`,
              })
            : null,
        ]),
        !provenance.stale_reason &&
        provenance.stage_status?.status === "up-to-date"
          ? el("span", { class: "badge ok", text: "current" })
          : null,
      ]),
    );
    if (provenance.source) {
      const source = el("a", {
        text: provenance.source,
        href: fileUrl(provenance.source),
        attrs: { target: "_blank" },
      });
      container.append(
        el(
          "div",
          { class: "small" },
          provenance.stage_kind === "manual-step"
            ? [document.createTextNode("Exported manually from "), source]
            : [
                document.createTextNode("Edit "),
                source,
                document.createTextNode(" to change it."),
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
  const body = el("div", { class: "tip" }, [loading()]);
  root.append(style, body);
  try {
    const provenance = await citationProvenance(link, item.citation);
    clear(body);
    renderProvenance(body, link, item.citation, provenance);
  } catch (e) {
    clear(body).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  }
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
  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.calkit !== "editor") {
      return;
    }
    const message = event.data as FromEditor;
    if (message.type === "citations") {
      editorCitations = { version: message.version, items: message.items };
      void checkCitations();
    } else if (message.type === "tooltip") {
      void fillTooltip(message.id, message.version, message.index);
    }
  });
}

/** Where a problem lands in the PDF, in points from the page's top left. */
interface PdfBox {
  page: number;
  h: number;
  v: number;
  width: number;
  height: number;
  message: string;
  line: number;
  column: number;
}

type SynctexBox = Omit<PdfBox, "message">;

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

function setBuildParams(params: URLSearchParams, build: PdfBuild): void {
  params.set("buildId", build.buildId);
  if (build.editorId) {
    params.set("editorId", build.editorId);
  }
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
    for (const box of kept) {
      boxes.push({ ...box, message: error.message });
    }
  }
  if (pdfBuild !== build || editorCitations !== snapshot) {
    return;
  }
  pdfBoxes = boxes;
  placePdfBoxes();
}

/**
 * Put a red box around each error on the PDF's pages.
 *
 * pdf.js clears a page it redraws, e.g., on zooming, so this runs whenever
 * the viewer changes, and leaves a page alone that already has its boxes.
 * A box's ``v`` is its bottom, e.g., a figure's baseline, and its height
 * goes up from there; for a scaled figure, it's the unscaled height.
 */
function placePdfBoxes(): void {
  const color = "#e5484d";
  for (const page of document.querySelectorAll<HTMLElement>(
    ".pdfViewer .page[data-page-number]",
  )) {
    const number = Number(page.dataset.pageNumber);
    const scale = parseFloat(
      getComputedStyle(page).getPropertyValue("--scale-factor"),
    );
    const wanted = Number.isFinite(scale)
      ? pdfBoxes.filter((box) => box.page === number)
      : [];
    const signature = `${scale}|${wanted
      .map((box) => [box.h, box.v, box.width, box.height].join(","))
      .join(";")}`;
    const existing = page.querySelectorAll(":scope > .calkit-pdf-box");
    if (
      existing.length === wanted.length &&
      page.dataset.calkitBoxes === signature
    ) {
      continue;
    }
    existing.forEach((node) => node.remove());
    page.dataset.calkitBoxes = signature;
    for (const box of wanted) {
      const tag = el("button", {
        text: box.message,
        title: `${box.message}. Click to show it in the editor.`,
        onClick: () =>
          toEditor({ type: "goto", line: box.line, column: box.column }),
      });
      Object.assign(tag.style, {
        position: "absolute",
        left: "-2px",
        bottom: "100%",
        maxWidth: "320px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        padding: "1px 5px",
        border: "none",
        borderRadius: "3px 3px 0 0",
        background: color,
        color: "#fff",
        font: "600 11px/1.4 -apple-system, BlinkMacSystemFont, sans-serif",
        cursor: "pointer",
        pointerEvents: "auto",
      });
      const outline = el("div", { class: "calkit-pdf-box" }, [tag]);
      Object.assign(outline.style, {
        position: "absolute",
        left: `${box.h * scale}px`,
        top: `${(box.v - box.height) * scale}px`,
        width: `${box.width * scale}px`,
        height: `${box.height * scale}px`,
        border: `2px solid ${color}`,
        borderRadius: "2px",
        boxSizing: "border-box",
        // Left to the PDF, so a double click still goes to the source
        pointerEvents: "none",
        zIndex: "5",
      });
      page.append(outline);
    }
  }
}

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
      placePdfBoxes();
    }, 200);
  }).observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["href"],
  });
  // A citation's provenance on hover, as in the editor. Overleaf says
  // which line of which file is under the pointer, as for a double click,
  // so the PDF still gets every click
  let shown: { index: number; version: number; host: HTMLElement } | null =
    null;
  let showing: ReturnType<typeof setTimeout> | undefined;
  let hiding: ReturnType<typeof setTimeout> | undefined;
  let lookups = 0;
  let tips = 0;
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
    if (!projectId || !snapshot || !file) {
      console.debug(
        "[Calkit] PDF hover: no .tex file selected in the file tree",
      );
      return null;
    }
    const params = new URLSearchParams({
      page: String(page),
      h: h.toFixed(2),
      v: v.toFixed(2),
    });
    if (!build) {
      console.debug("[Calkit] PDF hover: no PDF build found yet");
      return null;
    }
    setBuildParams(params, build);
    // Each pointer position is new, so there's nothing worth caching
    const code: { file: string; line: number; column?: number }[] = await fetch(
      `/project/${projectId}/sync/pdf?${params}`,
      { headers: { Accept: "application/json" } },
    )
      .then((response) => (response.ok ? response.json() : { code: [] }))
      .then((data) => data.code ?? [])
      .catch(() => []);
    for (const position of code) {
      // A root file in a folder comes back as, e.g., folder/./main.tex
      const at = position.file.replace(/(^|\/)\.\//g, "$1");
      if (at !== file) {
        continue;
      }
      const onLine = snapshot.items.flatMap((item, index) =>
        item.line === position.line ? [{ item, index }] : [],
      );
      if (!onLine.length) {
        continue;
      }
      // Usually there's no column, but when there is, take the nearest
      const column = position.column ?? -1;
      const best =
        column < 0
          ? onLine[0]
          : onLine.reduce((a, b) =>
              Math.abs(b.item.column - column) <
              Math.abs(a.item.column - column)
                ? b
                : a,
            );
      return { index: best.index, version: snapshot.version };
    }
    console.debug("[Calkit] PDF hover: no citation in", file, "at", code);
    return null;
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
      // Over the PDF, what's under the pointer once it rests decides
      clearTimeout(hiding);
      hiding = undefined;
      const bounds = page.getBoundingClientRect();
      const h = (event.clientX - bounds.left - page.clientLeft) / scale;
      const v = (event.clientY - bounds.top - page.clientTop) / scale;
      const number = Number(page.dataset.pageNumber);
      const { clientX, clientY } = event;
      showing = setTimeout(async () => {
        const lookup = ++lookups;
        const found = await citationAt(number, h, v);
        if (lookup !== lookups) {
          return;
        }
        if (!found) {
          hide();
        } else if (
          shown?.index !== found.index ||
          shown.version !== found.version
        ) {
          show(found, clientX, clientY);
        }
      }, 300);
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
          await send({ type: "overleaf.sync", owner, project, path });
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
    currentLink = link;
    void checkCitations();
    lastCheck = { overleafProjectId, hubWebUrl, link, status: statuses[0] };
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
    body.append(
      el("button", {
        class: "action secondary",
        text: "\u2190 Back",
        onClick: () => openPanel(overleafProjectId),
      }),
    );
    fill(body);
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
    // Cards link to the hub the project was found on, and can show before
    // the panel, which also sets it, is opened
    hubWebUrl = hub;
    currentLink = link;
    void checkCitations();
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

watchForSaves();
watchEditor();
watchPdf();
watchIntegrations();
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
