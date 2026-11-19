/**
 * Where a figure, table, or number comes from: its card, and the forms for
 * defining its origin, shown from the badge, the sidebar, and the PDF.
 */
import { type ImportSource, getImportSource } from "../core/detect";
import { renderPathPicker } from "../core/pickers";
import { projectUrl } from "../core/hub-url";
import {
  type Citation,
  canBeCreatedByPerson,
  citationProblems,
  getShownValue,
} from "../core/latex";
import { type Request, send } from "../core/messages";
import {
  type OverleafLinkPublic,
  type Provenance,
  type StageFromScriptOrNotebookResponse,
} from "../core/types";
import { clear, el, errorMessage, loading, textInput } from "../core/ui";
import {
  hubWebUrl,
  syncOwed,
  provenanceCache,
  provenanceFor,
  syncAfterHubChange,
  citationProvenance,
  linkKey,
  startRun,
  renderRuns,
  renderOpenLocally,
  showInPanel,
} from "./index";
import { problemLine, checkCitations } from "./citations";
import { showInRail } from "./sidebar";

/** All the data that can be uploaded with a script, as the hub allows. */
const MAX_SCRIPT_DATA_BYTES = 50_000_000;

/** A value as it reads in a panel row. */
export function valueText(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

/**
 * Make the stage that produces what the document shows, from the script
 * that makes it, uploaded or already in the project.
 *
 * The hub reads the script the way `calkit xr --dry-run` does, without
 * running it, so the user sees the environment, inputs, and outputs before
 * anything is committed. Overleaf can't run it, so once it's saved the
 * panel says how to, on the user's own machine. Something upstream, e.g.,
 * data a figure is made from, isn't in the document, so the stage has to
 * write it where it is.
 */
function renderAddScript(
  container: HTMLElement,
  link: OverleafLinkPublic,
  citation: Citation,
  shows: string,
  kind: "script" | "notebook",
  upstream: boolean,
  suggested?: string,
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
    placeholder: "Or find in project",
    accept: (p) => exts.some((ext) => p.toLowerCase().endsWith(ext)),
  });
  const read = el("button", { class: "action", text: `Read the ${kind}` });
  const message = el("div", { class: "small" });
  const review = el("div", { class: "stack", style: { marginTop: "6px" } });
  // On this machine, the script and its data are already in the project's
  // folder, so there's nothing to upload
  let isLocal = false;
  void send({ type: "local.checkout", project: `${owner}/${project}` })
    .then((local) => {
      if (local.path) {
        isLocal = true;
        file.style.display = "none";
        path.placeholder = "Find it in the project";
      }
    })
    .catch(() => undefined);
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
      fail(
        isLocal
          ? `Find the ${kind} in the project.`
          : `Choose the ${kind}, or find it in the project.`,
      );
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
  // machine, which is likely the one the script ran on
  const renderExternal = (
    external: string,
    detected: StageFromScriptOrNotebookResponse,
  ) => {
    const name = external.split(/[\\/]/).filter(Boolean).pop() ?? "data";
    // Copied in, with the script pointed at the copy, in one step
    if (isLocal) {
      const dest = textInput({ value: `data/${name}` });
      const note = el("div", { class: "small" });
      const copy = el("button", {
        class: "action",
        text: "Copy into project",
      });
      copy.addEventListener("click", async () => {
        if (!request) {
          return;
        }
        copy.disabled = true;
        clear(note).append(loading("Copying"));
        try {
          await send({
            type: "project.moveExternalData",
            owner,
            project,
            scriptPath: request.scriptPath,
            external,
            dest: dest.value.trim() || `data/${name}`,
          });
          await reread();
        } catch (e) {
          copy.disabled = false;
          clear(note).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
        }
      });
      return el("div", { class: "stack", style: { marginTop: "4px" } }, [
        el("div", {
          class: "small",
          style: { color: "var(--ck-warning)" },
          text:
            `Reads ${external}, outside the project, so it only runs on ` +
            `this machine. Copy it in, and ${request?.scriptPath} will ` +
            "read the copy:",
        }),
        dest,
        el("div", { class: "actions" }, [copy]),
        note,
      ]);
    }
    const chosen = data.get(external);
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
        "run on the machine it came from. Upload it to read it from the " +
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
    // Upstream, it's written where it is, even if Calkit didn't see the
    // script write it there, which the warning below says
    const choices = (upstream ? [shows] : detected.outputs).map((output) => {
      const radio = el("input", {
        type: "radio",
        attrs: { name: "ck-produces", value: output },
      });
      radio.checked = upstream || output === detected.produces;
      return { output, radio };
    });
    const citeNote = el("div", { class: "dim small" });
    const unseen = el("div", {
      class: "small",
      style: { color: "var(--ck-warning)" },
    });
    const chosen = () => choices.find((c) => c.radio.checked)?.output;
    const updateNote = () => {
      const output = chosen();
      citeNote.textContent =
        output && output !== shows
          ? `The paper will show it from there, with \\ckfigure{${output}}.`
          : "";
      // Static analysis can miss a path built at run time, so this warns
      // rather than refuses
      unseen.textContent =
        output && !(detected.found_outputs ?? []).includes(output)
          ? `Calkit didn't see ${request?.scriptPath} write ${output}. ` +
            "Check that it does, or the stage will fail when it runs."
          : "";
    };
    if (upstream) {
      // Nothing to choose
      review.append(unseen);
      updateNote();
    } else if (choices.length) {
      review.append(
        el("div", { class: "small dim", text: `Which output is ${shows}?` }),
        ...choices.map(({ output, radio }) => {
          radio.addEventListener("change", updateNote);
          return el("label", { class: "choice" }, [
            radio,
            el("span", { class: "name", text: output }),
          ]);
        }),
        citeNote,
        unseen,
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
      text: "Add to pipeline",
    });
    // A new stage hasn't run, so Overleaf can't sync until it has
    const runAfter = el("input", { type: "checkbox" }) as HTMLInputElement;
    runAfter.checked = true;
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
        await showDefined(container, link, citation);
        // Its run syncs after, which brings the \ckfigure into the editor
        if (runAfter.checked) {
          void startRun(link);
        }
        container.append(renderRunIt(saved, link, runAfter.checked));
      } catch (e) {
        fail(e);
        save.disabled = false;
      }
    });
    // Only a stage that makes what's shown defines its origin
    if (choices.length) {
      review.append(
        el("div", { class: "actions" }, [
          save,
          el("label", { class: "check" }, [
            runAfter,
            document.createTextNode("Run and sync"),
          ]),
        ]),
      );
    }
  };
  // A suggestion confirmed is read at once, to review before it's saved
  if (suggested) {
    path.value = suggested;
    queueMicrotask(() => read.click());
  }
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
  suggested?: string,
): HTMLElement {
  const owner = link.project_owner_name;
  const project = link.project_name;
  const file = el("input", { type: "file" });
  const { element: picker, input: path } = renderPathPicker({
    owner,
    project,
    placeholder: "Or find in project",
    accept: (p) => p !== target && canBeCreatedByPerson(p),
  });
  path.value = suggested ?? "";
  const appName = textInput({
    placeholder: "App it's exported with, e.g., Photoshop (optional)",
  });
  const save = el("button", { class: "action", text: "Add export step" });
  const message = el("div", { class: "small" });
  // On this machine, the file is already in the project's folder
  let isLocal = false;
  void send({ type: "local.checkout", project: `${owner}/${project}` })
    .then((local) => {
      if (local.path) {
        isLocal = true;
        file.style.display = "none";
        path.placeholder = "Find it in the project";
      }
    })
    .catch(() => undefined);
  const fail = (e: unknown) =>
    clear(message).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  save.addEventListener("click", async () => {
    clear(message);
    const upload = file.files?.[0];
    const typed = path.value.trim();
    if (!upload && !typed) {
      fail(
        isLocal
          ? "Find the file it's exported from in the project."
          : "Choose the file it's exported from, or find it in the project.",
      );
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

type ToRecord = Extract<Request, { type: "project.recordOrigin" }>;

/**
 * The ways to define where a file came from, each opening its form.
 *
 * A file only Overleaf has is synced into the project first, so what's
 * recorded about it lands on the file itself.
 */
function renderDefineOrigin(
  link: OverleafLinkPublic,
  citation: Citation,
  target: string,
  onlyInOverleaf = false,
  upstream = false,
): HTMLElement {
  let synced = !onlyInOverleaf;
  // Synced into the project first when only Overleaf has it, so what's
  // recorded lands on the file itself
  const prepare = async (): Promise<void> => {
    if (synced) {
      return;
    }
    await send({
      type: "overleaf.sync",
      owner: link.project_owner_name,
      project: link.project_name,
      path: link.path,
    });
    synced = true;
    // Found again now that it's in the project, e.g., figs/fit as
    // figs/fit.png
    provenanceCache.clear();
    target = (await citationProvenance(link, citation)).path;
  };
  const open = (form: (body: HTMLElement) => HTMLElement) =>
    showInPanel(async (body) => {
      if (!synced) {
        body.append(loading("Syncing from Overleaf"));
        try {
          await prepare();
        } catch (e) {
          clear(body).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
          return;
        }
        clear(body);
      }
      body.append(form(body));
    });
  // Created and imported take a click or a paste, right here
  const inline = el("div", { class: "stack", style: { marginTop: "6px" } });
  const fail = (e: unknown) =>
    clear(inline).append(
      errorMessage(e instanceof Error ? e.message : String(e)),
    );
  const record = async (
    origin: Pick<ToRecord, "importedFrom" | "createdBy">,
    done: string,
  ): Promise<void> => {
    clear(inline).append(loading("Saving"));
    try {
      await prepare();
      await send({
        type: "project.recordOrigin",
        owner: link.project_owner_name,
        project: link.project_name,
        path: target,
        ...origin,
      });
    } catch (e) {
      fail(e);
      return;
    }
    // One from a Git repo or project replaces the file on the hub, so
    // Overleaf gets it too
    if (origin.importedFrom?.project || origin.importedFrom?.git_repo_url) {
      clear(inline).append(loading("Syncing"));
      try {
        await syncAfterHubChange(link);
      } catch (e) {
        fail(
          `Saved, but not synced to Overleaf: ${
            e instanceof Error ? e.message : String(e)
          }. Update to try again.`,
        );
        return;
      }
    }
    provenanceCache.clear();
    void checkCitations();
    clear(inline).append(el("div", { class: "small dim", text: done }));
  };
  const showImport = () => {
    const input = textInput({ placeholder: "DOI, URL, or owner/project/path" });
    const hint = el("div", { class: "grow small dim" });
    const save = el("button", { class: "action", text: "Save" });
    const update = () => {
      const source = getImportSource(input.value);
      hint.textContent = source
        ? IMPORT_SOURCE_TEXT[source.kind]
        : input.value.trim()
        ? "Not a DOI, URL, or owner/project/path"
        : "";
      save.disabled = !source;
    };
    save.addEventListener("click", () => {
      const source = getImportSource(input.value);
      if (source) {
        void record(
          { importedFrom: source.importedFrom },
          `Imported from ${input.value.trim()}.`,
        );
      }
    });
    input.addEventListener("input", update);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !save.disabled) {
        save.click();
      }
    });
    update();
    clear(inline).append(input, el("div", { class: "row" }, [hint, save]));
    input.focus();
  };
  // Data is collected rather than created, e.g., in a lab
  const createdText = isData(target) ? "Collected" : "Created";
  const recordCreated = async () => {
    const user = (await send({ type: "auth.state" })).user;
    if (!user) {
      fail("Sign in to say you made it.");
      return;
    }
    await record(
      { createdBy: [{ email: user.email, name: user.full_name ?? null }] },
      `${createdText} by ${user.full_name || user.email}.`,
    );
  };
  const choices: [string, () => void][] = [
    [
      "Script",
      () =>
        open((body) =>
          renderAddScript(body, link, citation, target, "script", upstream),
        ),
    ],
    [
      "Notebook",
      () =>
        open((body) =>
          renderAddScript(body, link, citation, target, "notebook", upstream),
        ),
    ],
    ["Imported", showImport],
  ];
  // Something exported, e.g., a PNG, comes from a file a person made
  if (!canBeCreatedByPerson(target)) {
    choices.push([
      "Exported",
      () => open((body) => renderExported(body, link, citation, target)),
    ]);
  }
  if (canBeCreatedByPerson(target)) {
    choices.push([createdText, () => void recordCreated()]);
  }
  // What likely makes it, e.g., a notebook that writes it, read on this
  // machine, each opening its form filled in, to confirm
  const suggestions = el("div");
  void send({
    type: "project.originSuggestions",
    owner: link.project_owner_name,
    project: link.project_name,
    path: target,
  })
    .then((found) => {
      if (!found.length) {
        return;
      }
      suggestions.append(
        el("div", { class: "small dim", text: "Suggested" }),
        ...found.slice(0, 3).map((s) =>
          el("div", { class: "row", style: { marginTop: "4px" } }, [
            el("div", {
              class: "grow small",
              text:
                s.kind === "exported"
                  ? `Exported from ${s.source}`
                  : `Made by ${s.source}` +
                    (s.writes && s.writes !== target
                      ? `, which saves ${s.writes}`
                      : ""),
            }),
            el("button", {
              class: "action",
              text: "Confirm",
              onClick: () =>
                s.kind === "exported"
                  ? open((body) =>
                      renderExported(body, link, citation, target, s.source),
                    )
                  : open((body) =>
                      renderAddScript(
                        body,
                        link,
                        citation,
                        target,
                        s.kind === "notebook" ? "notebook" : "script",
                        upstream,
                        s.source,
                      ),
                    ),
            }),
          ]),
        ),
      );
    })
    .catch(() => {});
  // Two by two, everywhere, rather than one left over on a line of its own
  // where the row doesn't fit, e.g., in the panel
  return el("div", { style: { marginTop: "4px" } }, [
    suggestions,
    el("div", {
      class: "small dim",
      style: { marginTop: "4px" },
      // Named when it's what the cited file is made from
      text: upstream ? `Define origin for ${target}` : "Define origin",
    }),
    el(
      "div",
      {
        style: {
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "6px",
          marginTop: "4px",
        },
      },
      choices.map(([text, onClick]) =>
        el("button", { class: "action secondary", text, onClick }),
      ),
    ),
    inline,
  ]);
}

const IMPORT_SOURCE_TEXT: Record<ImportSource["kind"], string> = {
  doi: "DOI",
  git: "File in a Git repo",
  project: "File in a Calkit project",
  url: "Website",
};

/** Whether a path looks like data, e.g., a folder or a CSV file. */
function isData(path: string): boolean {
  const name = path.split("/").pop() ?? path;
  return (
    !name.includes(".") ||
    /\.(csv|tsv|json|xlsx?|h5|hdf5|nc|parquet|mat|npy|npz|dat|zarr)$/i.test(
      name,
    )
  );
}

/** How to run a stage that's never run, since Overleaf can't. */
function renderRunIt(
  saved: StageFromScriptOrNotebookResponse,
  link: OverleafLinkPublic,
  running: boolean,
): HTMLElement {
  const where = link.local_path ? "this machine" : "GitHub Actions";
  if (link.local_path || running) {
    return el("div", { class: "muted-box", style: { marginTop: "6px" } }, [
      el("div", {
        class: "small",
        text: running
          ? `Added stage ${saved.stage_name}. Running it on ${where}; ` +
            "its results come into this paper when it finishes:"
          : `Added stage ${saved.stage_name}. It hasn't run yet. Run it ` +
            `on ${where}, and its results come into this paper when it ` +
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
      text: "Or on your machine:",
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
export function renderProvenance(
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
  // Defined in the sidebar, under the component, for what it's made from
  // with no origin, which is often the component's own file
  const gapPaths = [
    ...new Set(problems.filter((p) => p.kind === "origin").map((p) => p.path)),
  ];
  if (gapPaths.length && link.current_user_access !== "read") {
    if (named) {
      container.append(
        el("div", { class: "small" }, [
          el("a", {
            text: "Define it in the Calkit sidebar",
            onClick: (event) => {
              event.preventDefault();
              showInRail(citation);
            },
          }),
        ]),
      );
    } else {
      for (const gap of gapPaths) {
        container.append(
          gapPaths.length > 1
            ? el("div", { class: "small", text: gap })
            : el("span"),
          renderDefineOrigin(
            link,
            citation,
            gap,
            // Only in Overleaf, so synced into the project first
            gap === provenance.path && !provenance.exists && !provenance.stage,
            // E.g., data it's made from, rather than what the document shows
            gap !== provenance.path && gap !== provenance.copied_from,
          ),
        );
      }
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
    if (provenance.updatable && link.current_user_access !== "read") {
      const message = el("div", { class: "small" });
      const update = el("button", {
        class: "action secondary",
        text: "Update",
        style: { padding: "4px 8px" },
      });
      update.addEventListener("click", async () => {
        update.disabled = true;
        clear(message).append(loading("Updating"));
        try {
          const updated = await send({
            type: "project.updateImport",
            owner: link.project_owner_name,
            project: link.project_name,
            path: provenance.path,
          });
          if (
            updated.changed ||
            syncOwed.has(`${linkKey(link)}:${link.path}`)
          ) {
            clear(message).append(loading("Syncing"));
            await syncAfterHubChange(link);
            await showDefined(container, link, citation);
          } else {
            clear(message).append(
              el("span", { class: "dim", text: "Already up to date" }),
            );
            update.disabled = false;
          }
        } catch (e) {
          clear(message).append(
            errorMessage(e instanceof Error ? e.message : String(e)),
          );
          update.disabled = false;
        }
      });
      container.append(
        el("div", { class: "actions", style: { marginTop: "4px" } }, [update]),
        message,
      );
    }
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
