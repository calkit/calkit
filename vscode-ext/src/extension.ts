import * as path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import * as vscode from "vscode";
import YAML from "yaml";

const COMMAND_SELECT_ENV = "calkit-vscode.selectCalkitEnvironment";
const SERVER_TERMINAL_NAME = "Calkit Notebook Server";
const execFileAsync = promisify(execFile);

let outputChannel: vscode.OutputChannel;

function log(message: string): void {
  if (outputChannel) {
    outputChannel.appendLine(message);
  }
}

type EnvKind =
  | "conda"
  | "docker"
  | "julia"
  | "matlab"
  | "pixi"
  | "renv"
  | "slurm"
  | "uv"
  | "uv-venv"
  | "venv"
  | "ssh"
  | "_system"
  | string;

interface CalkitEnvironment {
  kind: EnvKind;
  host?: string;
}

interface CalkitConfig {
  name?: string;
  environments?: Record<string, CalkitEnvironment>;
}

interface CalkitCandidate {
  label: string;
  description: string;
  detail: string;
  environmentName: string;
  innerEnvironment: string;
  innerKind: EnvKind;
  outerSlurmEnvironment?: string;
  outerKind?: EnvKind;
}

interface SlurmLaunchOptions {
  gpus?: string;
  time?: string;
  partition?: string;
  extra?: string;
}

export function activate(context: vscode.ExtensionContext): void {
  outputChannel = vscode.window.createOutputChannel("Calkit");
  log("Calkit extension activated");

  context.subscriptions.push(
    vscode.commands.registerCommand(COMMAND_SELECT_ENV, async () => {
      return await selectCalkitEnvironment();
    }),
  );

  // Proposed API: shows Calkit in the top-level kernel source list.
  // This must never break activation when proposed APIs are unavailable.
  registerKernelSourceIfAvailable(context);
}

export function deactivate(): void {
  // No-op
}

async function selectCalkitEnvironment(): Promise<string | undefined> {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    void vscode.window.showErrorMessage(
      "Open a workspace folder to use Calkit notebook environments.",
    );
    return undefined;
  }

  const config = await readCalkitConfig(workspaceRoot);
  if (!config?.environments || Object.keys(config.environments).length === 0) {
    void vscode.window.showErrorMessage(
      "No environments were found in calkit.yaml.",
    );
    return undefined;
  }

  const candidates = makeEnvironmentCandidates(config.environments);
  if (candidates.length === 0) {
    void vscode.window.showErrorMessage(
      "No notebook-capable Calkit environments were found.",
    );
    return undefined;
  }

  const picked = await vscode.window.showQuickPick(candidates, {
    placeHolder: "Select a Calkit environment for this notebook",
    matchOnDescription: true,
    matchOnDetail: true,
  });
  if (!picked) {
    return undefined;
  }

  // uv environments should only register/check the kernel and then select it.
  // No Jupyter server launch is needed for this path.
  if (picked.innerKind === "uv") {
    return await registerAndSelectKernel(
      workspaceRoot,
      picked.innerEnvironment,
      "-e",
    );
  }

  let slurmOptions: SlurmLaunchOptions | undefined;
  if (picked.outerSlurmEnvironment) {
    slurmOptions = await askForSlurmOptions();
    if (!slurmOptions) {
      return undefined;
    }
  }

  // For uv/julia in a non-nested setup, only register/check the kernel and
  // then select it in VS Code. No server launch is needed here.
  if (
    !picked.outerSlurmEnvironment &&
    needsKernelRegistration(picked.innerKind)
  ) {
    return await registerAndSelectKernel(
      workspaceRoot,
      picked.innerEnvironment,
      "-e",
    );
  }

  const port = getDefaultPort();
  const launchCmd = buildLaunchCommand(
    picked,
    workspaceRoot,
    config,
    port,
    slurmOptions,
  );

  const terminal =
    vscode.window.terminals.find((t) => t.name === SERVER_TERMINAL_NAME) ??
    vscode.window.createTerminal(SERVER_TERMINAL_NAME);
  terminal.show(true);
  terminal.sendText(launchCmd, true);

  const uri = `http://localhost:${port}/lab`;
  await vscode.env.clipboard.writeText(uri);

  const action = await vscode.window.showInformationMessage(
    `Launched Jupyter via Calkit. URI copied: ${uri}`,
    "Select Kernel",
    "Select Jupyter URI",
  );

  if (action === "Select Kernel") {
    await openKernelPicker();
  }

  if (action === "Select Jupyter URI") {
    await vscode.commands.executeCommand("jupyter.selectjupyteruri");
  }

  return undefined;
}

function getWorkspaceRoot(): string | undefined {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
}

async function readCalkitConfig(
  workspaceRoot: string,
): Promise<CalkitConfig | undefined> {
  try {
    const fileUri = vscode.Uri.file(path.join(workspaceRoot, "calkit.yaml"));
    const bytes = await vscode.workspace.fs.readFile(fileUri);
    const raw = Buffer.from(bytes).toString("utf8");
    const parsed = YAML.parse(raw) as CalkitConfig;
    return parsed;
  } catch (error) {
    void vscode.window.showErrorMessage(
      `Failed to read calkit.yaml: ${String(error)}`,
    );
    return undefined;
  }
}

function makeEnvironmentCandidates(
  environments: Record<string, CalkitEnvironment>,
): CalkitCandidate[] {
  const notebookKinds = new Set<EnvKind>([
    "conda",
    "docker",
    "julia",
    "matlab",
    "pixi",
    "renv",
    "uv",
    "uv-venv",
    "venv",
  ]);

  const standalone: CalkitCandidate[] = [];
  const slurmOuterNames: string[] = [];

  for (const [name, env] of Object.entries(environments)) {
    if (env.kind === "slurm") {
      slurmOuterNames.push(name);
      continue;
    }

    if (!notebookKinds.has(env.kind)) {
      continue;
    }

    standalone.push({
      label: name,
      description: env.kind,
      detail: "Run Jupyter server in this environment",
      environmentName: name,
      innerEnvironment: name,
      innerKind: env.kind,
    });
  }

  const nested: CalkitCandidate[] = [];
  for (const slurmOuter of slurmOuterNames) {
    for (const inner of standalone) {
      nested.push({
        label: `${slurmOuter}:${inner.environmentName}`,
        description: `slurm + ${inner.description}`,
        detail: "Run server with srun, then enter inner environment",
        environmentName: `${slurmOuter}:${inner.environmentName}`,
        innerEnvironment: inner.environmentName,
        innerKind: inner.innerKind,
        outerSlurmEnvironment: slurmOuter,
        outerKind: "slurm",
      });
    }
  }

  return [...standalone, ...nested];
}

async function askForSlurmOptions(): Promise<SlurmLaunchOptions | undefined> {
  const gpus = await vscode.window.showInputBox({
    title: "Slurm option: --gpus",
    prompt: "Optional GPU count or value (e.g. 1 or a100:1)",
    placeHolder: "leave blank to skip",
  });
  if (gpus === undefined) {
    return undefined;
  }

  const time = await vscode.window.showInputBox({
    title: "Slurm option: --time",
    prompt: "Optional time (e.g. 60 or 01:00:00)",
    placeHolder: "leave blank to skip",
  });
  if (time === undefined) {
    return undefined;
  }

  const partition = await vscode.window.showInputBox({
    title: "Slurm option: --partition",
    prompt: "Optional partition name",
    placeHolder: "leave blank to skip",
  });
  if (partition === undefined) {
    return undefined;
  }

  const extra = await vscode.window.showInputBox({
    title: "Additional srun options",
    prompt: "Optional raw options appended as-is (e.g. --cpus-per-task=8)",
    placeHolder: "leave blank to skip",
  });
  if (extra === undefined) {
    return undefined;
  }

  return { gpus, time, partition, extra };
}

function getDefaultPort(): number {
  const configured = vscode.workspace
    .getConfiguration("calkit.notebook")
    .get<number>("defaultJupyterPort", 8888);
  return configured > 0 ? configured : 8888;
}

function buildLaunchCommand(
  picked: CalkitCandidate,
  workspaceRoot: string,
  config: CalkitConfig,
  port: number,
  slurmOptions?: SlurmLaunchOptions,
): string {
  const cdPart = `cd ${shQuote(workspaceRoot)}`;
  const checkPart = `calkit check env -n ${shQuote(picked.innerEnvironment)}`;
  const kernelCheckPart = needsKernelRegistration(picked.innerKind)
    ? `calkit nb check-kernel -e ${shQuote(picked.innerEnvironment)}`
    : "";
  const slurmIpArg = picked.outerSlurmEnvironment ? " --ip=0.0.0.0" : "";
  const jupyterPart = `calkit jupyter lab --no-browser --ServerApp.token='' --ServerApp.password='' --port=${port}${slurmIpArg}`;
  const xenvPart = `calkit xenv -n ${shQuote(
    picked.innerEnvironment,
  )} -- ${jupyterPart}`;

  const prefixParts = [cdPart, checkPart];
  if (kernelCheckPart) {
    prefixParts.push(kernelCheckPart);
  }

  if (!picked.outerSlurmEnvironment) {
    // uv/julia kernels can be registered up front and used directly by Jupyter.
    if (needsKernelRegistration(picked.innerKind)) {
      return `${prefixParts.join(" && ")} && ${jupyterPart}`;
    }

    if (picked.innerKind === "docker") {
      void vscode.window.showInformationMessage(
        "Docker environments may need host networking for Jupyter access (for example via environment args).",
      );
    }
    return `${prefixParts.join(" && ")} && ${xenvPart}`;
  }

  const opts: string[] = [];
  if (slurmOptions?.gpus?.trim()) {
    opts.push(`--gpus=${slurmOptions.gpus.trim()}`);
  }
  if (slurmOptions?.time?.trim()) {
    opts.push(`--time=${slurmOptions.time.trim()}`);
  }
  if (slurmOptions?.partition?.trim()) {
    opts.push(`--partition=${slurmOptions.partition.trim()}`);
  }
  if (slurmOptions?.extra?.trim()) {
    opts.push(slurmOptions.extra.trim());
  }

  const host = config.environments?.[picked.outerSlurmEnvironment]?.host;
  if (host && host !== "localhost") {
    void vscode.window.showWarningMessage(
      `Outer SLURM environment host is '${host}'. The launch command will run locally; switch to that host first if needed.`,
    );
  }

  // For a SLURM outer environment, start the server directly under srun.
  const srunPart = `srun ${opts.join(" ")} ${jupyterPart}`.trim();
  return `${prefixParts.join(" && ")} && ${srunPart}`;
}

function needsKernelRegistration(kind: EnvKind): boolean {
  return kind === "uv" || kind === "julia";
}

async function registerAndSelectKernel(
  workspaceRoot: string,
  envName: string,
  envFlag: "-n" | "-e",
): Promise<string | undefined> {
  log(`Registering and selecting kernel for env: ${envName}`);

  try {
    const { stdout, stderr } = await execFileAsync(
      "calkit",
      ["nb", "check-kernel", envFlag, envName, "--json"],
      {
        cwd: workspaceRoot,
      },
    );

    log(`calkit output: ${stdout}`);

    let kernelName: string;
    let displayName: string | undefined;
    try {
      // Response may contain non-JSON output before the JSON.
      // Find and parse just the JSON object (line starting with {).
      const jsonMatch = stdout.match(/\{[\s\S]*\}/);
      if (!jsonMatch) {
        throw new Error("No JSON found in output");
      }
      const result = JSON.parse(jsonMatch[0]);
      kernelName = result.kernel_name;
      displayName = result.display_name;
      if (!kernelName) {
        throw new Error("kernel_name not in JSON response");
      }
      log(`Extracted kernel name: ${kernelName}`);
    } catch (parseError) {
      const details = `${stderr || stdout || String(parseError)}`.trim();
      log(`JSON parse error: ${details}`);
      void vscode.window.showErrorMessage(
        `Failed to parse kernel info from 'calkit nb check-kernel': ${details}`,
      );
      return undefined;
    }

    const selectedKernelId = await tryAutoSelectKernel(kernelName, displayName);

    if (selectedKernelId) {
      log(`Kernel selection successful`);
      void vscode.window.showInformationMessage(
        `Registered kernel '${kernelName}' and selected it for the active notebook.`,
      );
      return selectedKernelId;
    }

    log(`Kernel selection failed or unconfirmed`);
    void vscode.window.showInformationMessage(
      `Registered kernel '${kernelName}', but could not confirm auto-selection. Select the kernel manually from the picker.`,
    );
    return undefined;
  } catch (error: unknown) {
    const err = error as {
      stdout?: string;
      stderr?: string;
      message?: string;
    };
    const details = (err.stderr || err.stdout || err.message || "").trim();
    log(`Error: ${details}`);
    void vscode.window.showErrorMessage(
      `Failed to run 'calkit nb check-kernel ${envFlag} ${envName}': ${
        details || "unknown error"
      }`,
    );
    return undefined;
  }
}

async function tryAutoSelectKernel(
  kernelName: string,
  displayName?: string,
): Promise<string | undefined> {
  const editor = vscode.window.activeNotebookEditor;
  if (!editor) {
    log("No active notebook editor found for kernel selection");
    return undefined;
  }

  log(`Attempting to select kernel: ${kernelName}`);
  const editorId = getActiveNotebookEditorId() ?? "(none)";
  log(`Editor ID: ${editorId}`);

  const selectedKernelId = await trySelectKernelViaNotebookApi(
    editor,
    kernelName,
    displayName,
  );
  if (selectedKernelId) {
    log(`Successfully selected kernel controller: ${selectedKernelId}`);
    return selectedKernelId;
  }

  log(`Failed to select kernel: ${kernelName}`);
  return undefined;
}

async function trySelectKernelViaNotebookApi(
  editor: vscode.NotebookEditor,
  kernelName: string,
  displayName?: string,
): Promise<string | undefined> {
  type ResolvedKernel = {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  };

  try {
    const normalizedDisplay = (displayName ?? "").toLowerCase();
    const normalizedKernel = kernelName.toLowerCase();

    // Jupyter kernel discovery can lag behind check-kernel. Poll briefly.
    let candidate: ResolvedKernel | undefined;
    for (let attempt = 0; attempt < 10; attempt++) {
      const resolved = (await vscode.commands.executeCommand(
        "_resolveNotebookKernels",
        {
          viewType: editor.notebook.notebookType,
          uri: editor.notebook.uri,
        },
      )) as ResolvedKernel[];

      if (!Array.isArray(resolved) || resolved.length === 0) {
        log(
          `No kernels returned by _resolveNotebookKernels (attempt ${
            attempt + 1
          }/10)`,
        );
        await sleep(300);
        continue;
      }

      // Log compact resolved kernel information for debugging.
      const preview = resolved
        .slice(0, 12)
        .map(
          (k) =>
            `id='${k.id ?? ""}' label='${k.label ?? ""}' detail='${
              k.detail ?? ""
            }' desc='${k.description ?? ""}'`,
        )
        .join(" | ");
      log(`Resolved kernels (attempt ${attempt + 1}/10): ${preview}`);

      candidate = resolved.find((k) => {
        const id = (k.id ?? "").toLowerCase();
        const label = (k.label ?? "").toLowerCase();
        const desc = (k.description ?? "").toLowerCase();
        const detail = (k.detail ?? "").toLowerCase();
        const idCompact = id.replace(/[^a-z0-9]/g, "");
        const kernelCompact = normalizedKernel.replace(/[^a-z0-9]/g, "");
        const displayCompact = normalizedDisplay.replace(/[^a-z0-9]/g, "");

        return (
          id.endsWith(`/${normalizedKernel}`) ||
          id === normalizedKernel ||
          id.includes(normalizedKernel) ||
          (kernelCompact.length > 0 && idCompact.includes(kernelCompact)) ||
          (normalizedDisplay.length > 0 && label === normalizedDisplay) ||
          (normalizedDisplay.length > 0 && label.includes(normalizedDisplay)) ||
          (normalizedDisplay.length > 0 && desc.includes(normalizedDisplay)) ||
          (normalizedDisplay.length > 0 &&
            detail.includes(normalizedDisplay)) ||
          (displayCompact.length > 0 &&
            label.replace(/[^a-z0-9]/g, "").includes(displayCompact)) ||
          label.includes(normalizedKernel)
        );
      });

      if (candidate?.id) {
        break;
      }

      await sleep(300);
    }

    if (!candidate?.id) {
      log(
        `No matching controller found for kernel '${kernelName}' (${
          displayName ?? "no display name"
        })`,
      );
      return undefined;
    }

    const slash = candidate.id.indexOf("/");
    if (slash <= 0 || slash >= candidate.id.length - 1) {
      log(
        `Resolved controller id is not in extension/id format: ${candidate.id}`,
      );
      return undefined;
    }

    const extension = candidate.id.slice(0, slash);
    const id = candidate.id.slice(slash + 1);

    log(`Selecting controller id '${candidate.id}'`);
    await vscode.commands.executeCommand("notebook.selectKernel", {
      extension,
      id,
      notebookEditor: editor,
      skipIfAlreadySelected: false,
    });

    // Give VS Code/Jupyter time to bind the selected controller.
    await sleep(300);

    if (await isKernelSelectedForActiveNotebook(kernelName)) {
      return candidate.id;
    }
  } catch (err) {
    log(
      `Controller selection failed: ${
        err instanceof Error ? err.message : String(err)
      }`,
    );
  }

  return undefined;
}

async function isKernelSelectedForActiveNotebook(
  kernelName: string,
): Promise<boolean> {
  // Let Jupyter update notebook metadata after a kernel change.
  await sleep(250);
  const md = vscode.window.activeNotebookEditor?.notebook.metadata as any;
  const selectedName =
    md?.kernelspec?.name ?? md?.metadata?.kernelspec?.name ?? "";
  const notebookPath = vscode.window.activeNotebookEditor?.notebook.uri.fsPath;

  log(`Checking kernel selection - notebook: ${notebookPath}`);
  log(
    `Current kernel metadata: ${
      typeof selectedName === "string" ? selectedName : "(not set)"
    }`,
  );
  log(`Expected kernel: ${kernelName}`);

  // Check for exact match on the kernel name
  return typeof selectedName === "string" && selectedName === kernelName;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function getActiveNotebookEditorId(): string | undefined {
  const editorAny = vscode.window.activeNotebookEditor as
    | (vscode.NotebookEditor & { id?: string })
    | undefined;
  if (!editorAny?.id) {
    return undefined;
  }
  return editorAny.id;
}

async function openKernelPicker(): Promise<void> {
  if (!vscode.window.activeNotebookEditor) {
    void vscode.window.showWarningMessage(
      "Open a notebook editor first, then select a kernel.",
    );
    return;
  }

  const editorId = getActiveNotebookEditorId();
  const args = editorId ? { notebookEditorId: editorId } : undefined;
  try {
    if (args) {
      await vscode.commands.executeCommand("notebook.selectKernel", args);
    } else {
      await vscode.commands.executeCommand("notebook.selectKernel");
    }
  } catch {
    // Fallback to no-args invocation for VS Code versions that ignore args.
    await vscode.commands.executeCommand("notebook.selectKernel");
  }
}

function shQuote(input: string): string {
  return `'${input.replace(/'/g, `'\\''`)}'`;
}

function registerKernelSourceIfAvailable(
  context: vscode.ExtensionContext,
): void {
  try {
    const notebooksAny = vscode.notebooks as any;
    if (typeof notebooksAny.registerKernelSourceActionProvider !== "function") {
      return;
    }

    const provider = {
      provideNotebookKernelSourceActions: async () => {
        return [
          {
            label: "Calkit",
            detail: "Select a Calkit environment and kernel",
            command: {
              title: "Calkit",
              command: COMMAND_SELECT_ENV,
            },
          },
        ];
      },
    };

    context.subscriptions.push(
      notebooksAny.registerKernelSourceActionProvider(
        "jupyter-notebook",
        provider,
      ),
    );
  } catch (error) {
    console.warn(
      "Calkit: notebook kernel source proposal unavailable; using stable command/toolbar entry points only.",
      error,
    );
  }
}
