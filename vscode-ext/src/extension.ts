import * as path from "node:path";
import { execFile, spawn } from "node:child_process";
import { promisify } from "node:util";
import * as http from "node:http";
import * as https from "node:https";
import * as net from "node:net";
import * as vscode from "vscode";
import YAML from "yaml";

const COMMAND_SELECT_ENV = "calkit-vscode.selectCalkitEnvironment";
const execFileAsync = promisify(execFile);

let outputChannel: vscode.OutputChannel;
let serverProcess: import("node:child_process").ChildProcess | undefined;

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
  image?: string;
  platform?: string;
  env_vars?: Record<string, string>;
  gpus?: string;
  ports?: string[];
  user?: string;
  wdir?: string;
  args?: string[];
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

  // Docker and Slurm environments need tokenized servers
  const needsToken =
    picked.outerSlurmEnvironment || picked.innerKind === "docker";
  const serverToken = needsToken ? createServerToken() : undefined;
  const port = getDefaultPort();
  let dockerContainerName: string | undefined;
  if (!picked.outerSlurmEnvironment && picked.innerKind === "docker") {
    dockerContainerName = getManagedDockerContainerName(
      picked.innerEnvironment,
      port,
    );
    await stopManagedDockerContainerIfExists(dockerContainerName);
    const portIsFree = await waitForPortToBeFree(port, 7_000);
    if (!portIsFree) {
      void vscode.window.showErrorMessage(
        `Cannot start Docker notebook server: localhost:${port} is already in use. Stop the process using that port or change 'calkit.notebook.defaultJupyterPort'.`,
      );
      return undefined;
    }
  }

  const launchCmd = buildLaunchCommand(
    picked,
    workspaceRoot,
    config,
    port,
    slurmOptions,
    serverToken,
    dockerContainerName,
  );

  startServerInBackground(launchCmd, workspaceRoot);

  const uri = serverToken
    ? `http://localhost:${port}/lab?token=${encodeURIComponent(serverToken)}`
    : `http://localhost:${port}/lab`;
  await vscode.env.clipboard.writeText(uri);
  const kernelsBeforeConnect = await getResolvedKernelIdsForActiveNotebook();

  // Docker and Slurm environments require connecting to an existing server
  if (picked.outerSlurmEnvironment || picked.innerKind === "docker") {
    const envType = picked.outerSlurmEnvironment ? "Slurm" : "Docker";
    const isReady = await waitForServerReady(uri);
    const connected = isReady ? await selectExistingJupyterServer(uri) : false;

    // For Docker, we don't need to register a kernel separately since it should
    // be in the image, but we can try to select it if needed
    let selectedKernelId: string | undefined;
    if (picked.outerSlurmEnvironment) {
      selectedKernelId = await registerAndSelectKernel(
        workspaceRoot,
        picked.innerEnvironment,
        "-e",
      );
    } else if (picked.innerKind === "docker") {
      // After connecting to a Docker-backed server, try selecting a sensible
      // default kernel automatically before falling back to manual selection.
      selectedKernelId = await tryAutoSelectBestAvailableKernel({
        existingKernelIds: kernelsBeforeConnect,
        requireNewKernel: true,
      });
    }

    if (!connected) {
      void vscode.window.showWarningMessage(
        `${envType} server started, but VS Code could not auto-connect yet. URI copied: ${uri}`,
      );
    }

    const hasSelectedKernel = await hasAnyKernelSelectedForActiveNotebook();

    if (!selectedKernelId && !hasSelectedKernel) {
      void vscode.window
        .showInformationMessage(
          `Launched ${envType} Jupyter server. Select the kernel manually if needed.`,
          "Select Kernel",
        )
        .then(async (action) => {
          if (action === "Select Kernel") {
            await openKernelPicker();
          }
        });
    }

    return selectedKernelId;
  }

  const isReady = await waitForServerReady(uri);
  const connected = isReady ? await selectExistingJupyterServer(uri) : false;

  const action = await vscode.window.showInformationMessage(
    connected
      ? "Launched Jupyter via Calkit."
      : `Launched Jupyter via Calkit. Could not auto-connect yet; URI copied: ${uri}`,
    "Select Kernel",
  );

  if (action === "Select Kernel") {
    await openKernelPicker();
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
  const allNonSlurmInners: CalkitCandidate[] = [];
  const slurmOuterNames: string[] = [];

  for (const [name, env] of Object.entries(environments)) {
    if (env.kind === "slurm") {
      slurmOuterNames.push(name);
      continue;
    }

    // Any non-slurm environment can be used as an inner environment for a
    // slurm outer environment (for example: myslurm:py).
    allNonSlurmInners.push({
      label: name,
      description: env.kind,
      detail: "Run in this environment under a slurm outer environment",
      environmentName: name,
      innerEnvironment: name,
      innerKind: env.kind,
    });

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
    for (const inner of allNonSlurmInners) {
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
  serverToken?: string,
  dockerContainerName?: string,
): string {
  const cdPart = `cd ${shQuote(workspaceRoot)}`;
  const checkPart = `calkit check env -n ${shQuote(picked.innerEnvironment)}`;
  // All non-docker environments use kernel check; docker only needs env check
  const kernelCheckPart =
    picked.innerKind !== "docker"
      ? `calkit nb check-kernel -e ${shQuote(picked.innerEnvironment)}`
      : "";

  // Docker and Slurm need ip=0.0.0.0 and token for external access
  const needsExternalAccess =
    picked.outerSlurmEnvironment || picked.innerKind === "docker";
  const jupyterPart = needsExternalAccess
    ? `calkit jupyter lab --ip=0.0.0.0 --no-browser --port=${port}${
        serverToken ? ` --ServerApp.token=${shQuote(serverToken)}` : ""
      }`
    : `calkit jupyter lab --no-browser --ServerApp.token='' --ServerApp.password='' --port=${port}`;

  const xenvPart = `calkit xenv -n ${shQuote(
    picked.innerEnvironment,
  )} -- ${jupyterPart}`;

  const prefixParts = [cdPart];
  // Docker only needs env check; all others only need kernel check
  if (picked.innerKind === "docker") {
    prefixParts.push(checkPart);
  } else {
    prefixParts.push(kernelCheckPart);
  }

  if (!picked.outerSlurmEnvironment) {
    // uv/julia kernels can be registered up front and used directly by Jupyter.
    if (needsKernelRegistration(picked.innerKind)) {
      return `${prefixParts.join(" && ")} && ${jupyterPart}`;
    }

    // Docker environments launch Jupyter inside the container
    if (picked.innerKind === "docker") {
      return buildDockerRunCommand(
        picked,
        workspaceRoot,
        config,
        port,
        serverToken,
        dockerContainerName,
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

  // For a SLURM outer environment, run jupyter directly under srun.
  // No need for calkit xenv wrapper - srun provides the environment context.
  // Use --kill-on-bad-exit to ensure cleanup when srun is interrupted.
  const rawJupyterCmd = `jupyter lab --ip=0.0.0.0 --no-browser --port=${port}${
    serverToken ? ` --ServerApp.token=${shQuote(serverToken)}` : ""
  }`;
  const srunPart = `srun --kill-on-bad-exit ${opts.join(
    " ",
  )} ${rawJupyterCmd}`.trim();
  return `${prefixParts.join(" && ")} && ${srunPart}`;
}

function buildDockerRunCommand(
  picked: CalkitCandidate,
  workspaceRoot: string,
  config: CalkitConfig,
  port: number,
  serverToken?: string,
  containerName?: string,
): string {
  const env = config.environments?.[picked.innerEnvironment];
  if (!env) {
    throw new Error(`Environment ${picked.innerEnvironment} not found`);
  }

  const image = env.image || picked.innerEnvironment;
  const wdir = env.wdir || "/work";

  const dockerArgs: string[] = ["docker", "run"];

  // Platform
  if (env.platform) {
    dockerArgs.push("--platform", env.platform);
  }

  // Environment variables
  if (env.env_vars) {
    for (const [key, value] of Object.entries(env.env_vars)) {
      dockerArgs.push("-e", `${key}=${value}`);
    }
  }

  // GPUs
  if (env.gpus) {
    dockerArgs.push("--gpus", env.gpus);
  }

  // Port mapping - ensure Jupyter port is mapped
  const portMapped = env.ports?.some((p) => p.includes(`${port}`));
  if (!portMapped) {
    dockerArgs.push("-p", `${port}:${port}`);
  }
  if (env.ports) {
    for (const portSpec of env.ports) {
      // Skip if we already added this port
      if (!portSpec.includes(`${port}`)) {
        dockerArgs.push("-p", portSpec);
      }
    }
  }

  // User mapping (defaults to current user)
  if (env.user !== undefined) {
    dockerArgs.push("--user", env.user);
  }

  // Additional args from environment config
  if (env.args) {
    dockerArgs.push(...env.args);
  }

  // Standard docker run flags for background execution
  dockerArgs.push("--rm");
  if (containerName) {
    dockerArgs.push("--name", containerName);
  }

  // Working directory and volume mount
  dockerArgs.push("-w", wdir);
  dockerArgs.push("-v", `${workspaceRoot}:${wdir}`);

  // Image name
  dockerArgs.push(image);

  // Jupyter command (no need for --ip=0.0.0.0 with port mapping)
  const tokenArg = serverToken
    ? `--ServerApp.token=${shQuote(serverToken)}`
    : "";
  dockerArgs.push(
    "sh",
    "-c",
    `jupyter lab --no-browser --port=${port} ${tokenArg}`.trim(),
  );

  const dockerCmd = dockerArgs.map(shQuote).join(" ");

  // Prepend environment check to lock the environment
  const cdPart = `cd ${shQuote(workspaceRoot)}`;
  const checkPart = `calkit check env -n ${shQuote(picked.innerEnvironment)}`;

  return `${cdPart} && ${checkPart} && ${dockerCmd}`;
}

function needsKernelRegistration(kind: EnvKind): boolean {
  return kind === "uv" || kind === "julia";
}

function createServerToken(): string {
  return `calkit-${Math.random().toString(36).slice(2, 12)}`;
}

function getManagedDockerContainerName(envName: string, port: number): string {
  const safeEnv = envName.toLowerCase().replace(/[^a-z0-9_.-]/g, "-");
  return `calkit-nb-${safeEnv}-${port}`;
}

async function stopManagedDockerContainerIfExists(
  containerName: string,
): Promise<void> {
  try {
    await execFileAsync("docker", ["rm", "-f", containerName]);
    log(`Removed existing managed Docker container: ${containerName}`);
  } catch {
    // Container not found or not running; nothing to do.
  }
}

async function waitForPortToBeFree(
  port: number,
  timeoutMs = 5_000,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isPortFree(port)) {
      return true;
    }
    await sleep(250);
  }
  return false;
}

async function isPortFree(port: number): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    const server = net.createServer();
    server.unref();

    server.once("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "EADDRINUSE") {
        resolve(false);
      } else {
        resolve(false);
      }
    });

    server.listen(port, "127.0.0.1", () => {
      server.close(() => resolve(true));
    });
  });
}

async function selectExistingJupyterServer(uri: string): Promise<boolean> {
  // Try a few command shapes; Jupyter command contracts vary across versions.
  const attempts: Array<{ command: string; args: unknown[] }> = [
    { command: "jupyter.selectjupyteruri", args: [uri] },
    { command: "jupyter.selectjupyteruri", args: [{ uri }] },
    { command: "jupyter.commandLineSelectJupyterURI", args: [uri] },
    { command: "jupyter.selectjupyteruri", args: [] },
  ];

  for (const attempt of attempts) {
    try {
      await vscode.commands.executeCommand(attempt.command, ...attempt.args);
      return true;
    } catch {
      // Try next command signature.
    }
  }

  return false;
}

async function waitForServerReady(
  uri: string,
  timeoutMs = 45_000,
  pollMs = 1_000,
): Promise<boolean> {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (await isHttpEndpointReachable(uri)) {
      return true;
    }
    await sleep(pollMs);
  }
  return false;
}

async function isHttpEndpointReachable(targetUrl: string): Promise<boolean> {
  return await new Promise<boolean>((resolve) => {
    let parsed: URL;
    try {
      parsed = new URL(targetUrl);
    } catch {
      resolve(false);
      return;
    }

    const client = parsed.protocol === "https:" ? https : http;
    const req = client.request(
      {
        method: "GET",
        hostname: parsed.hostname,
        port: parsed.port,
        path: `${parsed.pathname}${parsed.search}`,
        timeout: 1_500,
      },
      (res) => {
        // Any HTTP response means the server is accepting connections.
        res.resume();
        resolve(true);
      },
    );

    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
    req.on("error", () => resolve(false));
    req.end();
  });
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

async function tryAutoSelectBestAvailableKernel(options?: {
  existingKernelIds?: Set<string>;
  requireNewKernel?: boolean;
}): Promise<string | undefined> {
  const editor = vscode.window.activeNotebookEditor;
  if (!editor) {
    return undefined;
  }

  type ResolvedKernel = {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  };

  const languageHint = getNotebookLanguageHint(editor).toLowerCase();
  const existingIds = options?.existingKernelIds ?? new Set<string>();
  const requireNewKernel = options?.requireNewKernel ?? false;

  for (let attempt = 0; attempt < 15; attempt++) {
    const resolved = await getResolvedNotebookKernels(editor);

    if (!Array.isArray(resolved) || resolved.length === 0) {
      await sleep(400);
      continue;
    }

    const candidates = resolved.filter((k) => {
      const id = k.id ?? "";
      return id.includes("/");
    });

    const newCandidates = candidates.filter((k) => {
      const id = k.id ?? "";
      return id.length > 0 && !existingIds.has(id);
    });

    const candidatePool = newCandidates.length > 0 ? newCandidates : candidates;
    if (requireNewKernel && newCandidates.length === 0) {
      await sleep(400);
      continue;
    }

    const sorted = [...candidatePool].sort((a, b) => {
      const sa = scoreKernelCandidate(a, languageHint);
      const sb = scoreKernelCandidate(b, languageHint);
      return sb - sa;
    });

    for (const candidate of sorted) {
      const id = candidate.id ?? "";
      const slash = id.indexOf("/");
      if (slash <= 0 || slash >= id.length - 1) {
        continue;
      }

      const extension = id.slice(0, slash);
      const controllerId = id.slice(slash + 1);

      try {
        await vscode.commands.executeCommand("notebook.selectKernel", {
          extension,
          id: controllerId,
          notebookEditor: editor,
          skipIfAlreadySelected: false,
        });
        await sleep(400);

        if (await hasAnyKernelSelectedForActiveNotebook()) {
          log(`Auto-selected best available kernel: ${id}`);
          return id;
        }
      } catch {
        // Try next candidate.
      }
    }

    await sleep(400);
  }

  return undefined;
}

function scoreKernelCandidate(
  kernel: {
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  },
  languageHint: string,
): number {
  const id = (kernel.id ?? "").toLowerCase();
  const label = (kernel.label ?? "").toLowerCase();
  const desc = (kernel.description ?? "").toLowerCase();
  const detail = (kernel.detail ?? "").toLowerCase();

  let score = 0;

  if (id.startsWith("ms-toolsai.jupyter/")) {
    score += 50;
  }

  if (languageHint.length > 0) {
    if (
      label.includes(languageHint) ||
      desc.includes(languageHint) ||
      detail.includes(languageHint)
    ) {
      score += 100;
    }
  }

  if (
    languageHint === "python" &&
    (label.includes("ipykernel") || label.includes("python"))
  ) {
    score += 30;
  }
  if (languageHint === "julia" && label.includes("julia")) {
    score += 30;
  }
  if (languageHint === "r" && label.includes("r")) {
    score += 30;
  }

  return score;
}

function getNotebookLanguageHint(editor: vscode.NotebookEditor): string {
  const metadata = editor.notebook.metadata as any;
  const fromMetadata =
    metadata?.language_info?.name ?? metadata?.metadata?.language_info?.name;
  if (typeof fromMetadata === "string" && fromMetadata.trim()) {
    return fromMetadata.trim();
  }

  const firstCodeCell = editor.notebook
    .getCells()
    .find((cell) => cell.kind === vscode.NotebookCellKind.Code);
  if (firstCodeCell?.document.languageId) {
    return firstCodeCell.document.languageId;
  }

  return "";
}

async function getResolvedNotebookKernels(
  editor: vscode.NotebookEditor,
): Promise<
  Array<{ id?: string; label?: string; description?: string; detail?: string }>
> {
  const resolved = (await vscode.commands.executeCommand(
    "_resolveNotebookKernels",
    {
      viewType: editor.notebook.notebookType,
      uri: editor.notebook.uri,
    },
  )) as Array<{
    id?: string;
    label?: string;
    description?: string;
    detail?: string;
  }>;
  return Array.isArray(resolved) ? resolved : [];
}

async function getResolvedKernelIdsForActiveNotebook(): Promise<Set<string>> {
  const editor = vscode.window.activeNotebookEditor;
  if (!editor) {
    return new Set<string>();
  }

  const kernels = await getResolvedNotebookKernels(editor);
  const ids = kernels
    .map((k) => k.id)
    .filter((id): id is string => typeof id === "string" && id.length > 0);
  return new Set(ids);
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

async function hasAnyKernelSelectedForActiveNotebook(): Promise<boolean> {
  // Give Jupyter a brief moment to attach kernelspec metadata after connect.
  await sleep(200);
  const md = vscode.window.activeNotebookEditor?.notebook.metadata as any;
  const selectedName =
    md?.kernelspec?.name ?? md?.metadata?.kernelspec?.name ?? "";
  return typeof selectedName === "string" && selectedName.trim().length > 0;
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

function startServerInBackground(command: string, cwd: string): void {
  if (
    serverProcess &&
    serverProcess.exitCode === null &&
    !serverProcess.killed
  ) {
    log("Stopping previous Calkit server process");
    serverProcess.kill();
  }

  log(`Starting server in background: ${command}`);
  const child = spawn(command, {
    cwd,
    shell: true,
    env: process.env,
  });
  serverProcess = child;

  child.stdout?.on("data", (chunk: Buffer | string) => {
    const text = chunk.toString().trim();
    if (text) {
      log(`[server] ${text}`);
    }
  });

  child.stderr?.on("data", (chunk: Buffer | string) => {
    const text = chunk.toString().trim();
    if (text) {
      log(`[server:err] ${text}`);
    }
  });

  child.on("error", (error) => {
    log(`Background server failed to start: ${String(error)}`);
    void vscode.window.showErrorMessage(
      `Failed to start Calkit notebook server in background: ${String(error)}`,
    );
  });

  child.on("close", (code, signal) => {
    log(
      `Background server exited (code=${code ?? "null"}, signal=${
        signal ?? "null"
      })`,
    );
    if (serverProcess === child) {
      serverProcess = undefined;
    }
  });
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
