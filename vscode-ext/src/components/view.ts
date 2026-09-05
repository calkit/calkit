import * as vscode from "vscode";
import {
  componentDiagnostics,
  componentsByLine,
  diagnosticSpan,
  questionDiagnostics,
  figureComponent,
  definitionLine,
  hoverLines,
  isLatexDocument,
  lensStages,
  objectLensTarget,
  objectLensTitle,
  lensTitle,
  stageLensTitle,
  toAbsolute,
  withCheckedStatus,
} from "./core";
import type { Component, DocumentComponents, QuestionsReport } from "./core";
import {
  extractLatexImageRefs,
  extractMarkdownImageRefs,
  resolveFigureRefStage,
  resolveImageRefToRepoRelative,
} from "../figures/core";

// Editor surfaces for the project content a document injects: what is under
// the cursor, where it came from, and whether it still matches the project.
//
// All of it comes from `calkit describe components --json`, so the tie between
// a place in the source and a results file lives in one implementation shared
// with the hub and the browser extension. The optimal loop this exists for is:
// hover a number, jump to the script that computes it, tweak, come back.

export interface ComponentsDeps {
  getWorkspaceRoot: () => string | undefined;
  // Runs `calkit describe components` with the given arguments, returning
  // parsed JSON, or undefined if the call failed (no project, no calkit on
  // PATH, a document the resolver can't place).
  describeComponents: (
    workspaceRoot: string,
    args: string[],
  ) => Promise<DocumentComponents | undefined>;
  runStageCommand: string;
  // Opens a stage in the sidebar, where its script, inputs and outputs
  // are. Takes the stage's name.
  viewStageCommand: string;
  // Opens what a line uses in the sidebar: an artifact by path, or a
  // question by its number.
  viewComponentObjectCommand: string;
  // Where component problems are reported. Optional so a caller that only
  // wants hovers and lenses need not make one.
  diagnostics?: vscode.DiagnosticCollection;
  // Runs `calkit check questions --json`, for the faults that live in
  // calkit.yaml rather than in a document.
  checkQuestions?: (
    workspaceRoot: string,
  ) => Promise<QuestionsReport | undefined>;
  // Output path -> producing stage, for documents the resolver can't read
  buildOutputToStageMap: (
    workspaceRoot: string,
  ) => Promise<Map<string, string>>;
  log: (message: string) => void;
}

// The whole-document listing is what carries pipeline status, and that shells
// out to DVC, so it is fetched at most this often per document. Hovers stay
// responsive by asking for the cursor position with the check skipped and
// folding in whatever this last saw.
const LISTING_TTL_MS = 30_000;

const DIAGNOSTIC_SEVERITIES = {
  error: vscode.DiagnosticSeverity.Error,
  warning: vscode.DiagnosticSeverity.Warning,
  info: vscode.DiagnosticSeverity.Information,
} as const;

export class ComponentsProvider
  implements
    vscode.HoverProvider,
    vscode.DefinitionProvider,
    vscode.DeclarationProvider,
    vscode.CodeLensProvider
{
  private readonly _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;
  // Per document: the last whole-document listing and when it was taken
  private readonly listings = new Map<
    string,
    { at: number; components: Component[] }
  >();

  constructor(private readonly deps: ComponentsDeps) {}

  // Called when calkit.yaml, dvc.lock or a document changes: the next lens or
  // hover asks again rather than answering from a stale reading.
  refresh(): void {
    this.listings.clear();
    this._onDidChangeCodeLenses.fire();
  }

  /**
   * Report a document's stale, missing and unaccounted-for components.
   *
   * A hover has to be asked and a lens has to be scrolled to. Neither finds
   * the paragraph on page nine whose number moved, so the same readings go
   * into Problems, where the editor counts them and a writer sees there is
   * something to look at without going looking.
   */
  async updateDiagnostics(document: vscode.TextDocument): Promise<void> {
    const collection = this.deps.diagnostics;
    if (!collection) {
      return;
    }
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (
      !workspaceRoot ||
      !isLatexDocument(document.uri.fsPath, document.languageId)
    ) {
      return;
    }
    const relPath = vscode.workspace
      .asRelativePath(document.uri, false)
      .replace(/\\/g, "/");
    const components = await this.listing(workspaceRoot, relPath);
    if (!components) {
      // Nothing was read, which is not the same as nothing being wrong:
      // leave whatever was last reported rather than claiming it is clean
      return;
    }
    collection.set(
      document.uri,
      componentDiagnostics(components, relPath)
        .filter((found) => found.line < document.lineCount)
        .map((found) => {
          const lineText = document.lineAt(found.line).text;
          const length = diagnosticSpan(lineText, found.column);
          const diagnostic = new vscode.Diagnostic(
            new vscode.Range(
              found.line,
              found.column,
              found.line,
              Math.min(found.column + length, lineText.length),
            ),
            found.message,
            DIAGNOSTIC_SEVERITIES[found.severity],
          );
          diagnostic.source = "calkit";
          return diagnostic;
        }),
    );
  }

  /**
   * Report what `calkit check questions` finds, in `calkit.yaml` itself.
   *
   * A placeholder nothing fills, or evidence that has moved since the
   * answer was written, is about the question rather than the paper that
   * typesets it, so it belongs on the line that declares it. Neither says
   * the answer is wrong: the second one says to read it again. The
   * document side of the same reading is a `\ckfindings` block marked
   * `answer-stale`, which `updateDiagnostics` already reports.
   */
  async updateQuestionDiagnostics(
    document: vscode.TextDocument,
  ): Promise<void> {
    const collection = this.deps.diagnostics;
    const check = this.deps.checkQuestions;
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (!collection || !check || !workspaceRoot) {
      return;
    }
    const report = await check(workspaceRoot);
    if (!report) {
      return;
    }
    const text = document.getText();
    collection.set(
      document.uri,
      questionDiagnostics(report, text)
        .filter((found) => found.line < document.lineCount)
        .map((found) => {
          const line = document.lineAt(found.line);
          const diagnostic = new vscode.Diagnostic(
            line.range,
            found.message,
            DIAGNOSTIC_SEVERITIES[found.severity],
          );
          diagnostic.source = "calkit";
          return diagnostic;
        }),
    );
  }

  private async listing(
    workspaceRoot: string,
    relPath: string,
  ): Promise<Component[] | undefined> {
    const cached = this.listings.get(relPath);
    if (cached && Date.now() - cached.at < LISTING_TTL_MS) {
      return cached.components;
    }
    const result = await this.deps.describeComponents(workspaceRoot, [
      "--source",
      relPath,
      "--json",
    ]);
    if (!result) {
      return cached?.components;
    }
    this.listings.set(relPath, {
      at: Date.now(),
      components: result.components,
    });
    return result.components;
  }

  // The components at one position, with the pipeline's verdict folded in
  // from the cached listing.
  private async at(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<{ workspaceRoot: string; components: Component[] } | undefined> {
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (
      !workspaceRoot ||
      !isLatexDocument(document.uri.fsPath, document.languageId)
    ) {
      return undefined;
    }
    const relPath = vscode.workspace
      .asRelativePath(document.uri, false)
      .replace(/\\/g, "/");
    const found = await this.deps.describeComponents(workspaceRoot, [
      "--source",
      relPath,
      "--line",
      String(position.line + 1),
      "--column",
      String(position.character + 1),
      "--no-stage-check",
      "--json",
    ]);
    if (!found || found.components.length === 0) {
      return undefined;
    }
    return {
      workspaceRoot,
      components: withCheckedStatus(
        found.components,
        await this.listing(workspaceRoot, relPath),
      ),
    };
  }

  async provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.Hover | undefined> {
    const at = await this.at(document, position);
    if (!at) {
      return undefined;
    }
    const md = new vscode.MarkdownString();
    md.isTrusted = true;
    md.supportThemeIcons = true;
    at.components.forEach((component, index) => {
      if (index > 0) {
        md.appendMarkdown("\n\n---\n\n");
      }
      md.appendMarkdown(hoverLines(component).join("\n\n"));
      const links: string[] = [];
      const fileUri = vscode.Uri.file(
        toAbsolute(at.workspaceRoot, component.path),
      );
      links.push(`[Open file](${fileUri.toString()})`);
      if (component.script) {
        const scriptUri = vscode.Uri.file(
          toAbsolute(at.workspaceRoot, component.script),
        );
        links.push(`[Open script](${scriptUri.toString()})`);
      }
      // Into the sidebar, which is where the project says what a thing is
      // and where a figure's origin gets recorded. Same two destinations
      // the lens offers, for whoever hovered instead of looking up.
      const target = objectLensTarget([component]);
      if (target !== undefined) {
        const args = encodeURIComponent(JSON.stringify([target]));
        links.push(
          `[Show in sidebar](command:${this.deps.viewComponentObjectCommand}` +
            `?${args})`,
        );
      }
      if (component.stage) {
        const args = encodeURIComponent(JSON.stringify([component.stage]));
        links.push(
          `[Show stage](command:${this.deps.viewStageCommand}?${args})`,
        );
        links.push(`[Run stage](command:${this.deps.runStageCommand}?${args})`);
      }
      md.appendMarkdown(`\n\n${links.join(" · ")}`);
    });
    return new vscode.Hover(md);
  }

  // F12 on a value or figure opens what it came from: the results file at the
  // key, or the figure itself.
  async provideDefinition(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.Location[] | undefined> {
    const at = await this.at(document, position);
    if (!at) {
      return undefined;
    }
    return this.locations(
      at.workspaceRoot,
      at.components.map((c) => ({ path: c.path, key: c.key })),
    );
  }

  // Go to declaration opens the script that produces it, which is the one
  // keystroke that matters: change the number, come back to the paragraph.
  async provideDeclaration(
    document: vscode.TextDocument,
    position: vscode.Position,
  ): Promise<vscode.Location[] | undefined> {
    const at = await this.at(document, position);
    if (!at) {
      return undefined;
    }
    return this.locations(
      at.workspaceRoot,
      at.components
        .filter((c) => c.script)
        .map((c) => ({ path: c.script as string, key: null })),
    );
  }

  private async locations(
    workspaceRoot: string,
    targets: { path: string; key: string | null }[],
  ): Promise<vscode.Location[] | undefined> {
    const locations: vscode.Location[] = [];
    const seen = new Set<string>();
    for (const target of targets) {
      const uri = vscode.Uri.file(toAbsolute(workspaceRoot, target.path));
      let line = 0;
      if (target.key) {
        try {
          const text = Buffer.from(
            await vscode.workspace.fs.readFile(uri),
          ).toString("utf8");
          line = definitionLine(text, target.key) ?? 0;
        } catch (error) {
          // A DVC-tracked file that hasn't been pulled has no content to
          // search; opening it at the top still beats not navigating
          this.deps.log(`Could not read ${target.path}: ${String(error)}`);
        }
      }
      const key = `${uri.fsPath}:${line}`;
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      locations.push(new vscode.Location(uri, new vscode.Position(line, 0)));
    }
    return locations.length > 0 ? locations : undefined;
  }

  // A lens on each line that injects something, saying which stage is behind
  // it and flagging anything out of date or unaccounted for. The listing
  // carries where each component is written, so this costs one call for the
  // whole document rather than one per line.
  async provideCodeLenses(
    document: vscode.TextDocument,
  ): Promise<vscode.CodeLens[]> {
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (!workspaceRoot) {
      return [];
    }
    const relPath = vscode.workspace
      .asRelativePath(document.uri, false)
      .replace(/\\/g, "/");
    const components = isLatexDocument(document.uri.fsPath, document.languageId)
      ? await this.listing(workspaceRoot, relPath)
      : await this.figureComponents(workspaceRoot, document, relPath);
    if (!components || components.length === 0) {
      return [];
    }
    const lenses: vscode.CodeLens[] = [];
    for (const [line, onLine] of componentsByLine(components, relPath)) {
      if (line >= document.lineCount) {
        continue;
      }
      const range = new vscode.Range(line, 0, line, 0);
      // What is wrong, if anything, and running the stage that would fix
      // it. Without a stage there is nothing to run, so the lens reports.
      const title = lensTitle(onLine);
      if (title !== undefined) {
        const stage = onLine.find((c) => c.status !== "ok" && c.stage)?.stage;
        lenses.push(
          new vscode.CodeLens(range, {
            title,
            command: stage ? this.deps.runStageCommand : "",
            arguments: stage ? [stage] : undefined,
          }),
        );
      }
      // Where it came from: the sidebar, which is where the script, the
      // inputs and the outputs are
      const stageTitle = stageLensTitle(onLine);
      const stages = lensStages(onLine);
      if (stageTitle !== undefined) {
        lenses.push(
          new vscode.CodeLens(range, {
            title: stageTitle,
            tooltip: "Open this stage in the Calkit sidebar",
            command: this.deps.viewStageCommand,
            arguments: [stages[0]],
          }),
        );
      }
      // What it is, as the project declares it. The place a figure's
      // origin gets recorded, and the only lens a question block gets.
      const objectTitle = objectLensTitle(onLine);
      const objectTarget = objectLensTarget(onLine);
      if (objectTitle !== undefined && objectTarget !== undefined) {
        lenses.push(
          new vscode.CodeLens(range, {
            title: objectTitle,
            tooltip: "Open this in the Calkit sidebar",
            command: this.deps.viewComponentObjectCommand,
            arguments: [objectTarget],
          }),
        );
      }
    }
    return lenses;
  }

  // Quarto and Markdown have no provenance record to read, so the figures
  // they reference are resolved the only way available: by asking which
  // stage produces the path. Same lens, less to say on it.
  private async figureComponents(
    workspaceRoot: string,
    document: vscode.TextDocument,
    relPath: string,
  ): Promise<Component[]> {
    const text = document.getText();
    const refs = /\.tex$/i.test(document.uri.fsPath)
      ? extractLatexImageRefs(text)
      : extractMarkdownImageRefs(text);
    if (refs.length === 0) {
      return [];
    }
    const outputToStage = await this.deps.buildOutputToStageMap(workspaceRoot);
    const components: Component[] = [];
    for (const ref of refs) {
      const path = resolveImageRefToRepoRelative(
        document.uri.fsPath,
        ref.target,
        workspaceRoot,
      );
      if (!path) {
        continue;
      }
      components.push(
        figureComponent(
          path,
          resolveFigureRefStage(path, outputToStage),
          relPath,
          ref.line + 1,
        ),
      );
    }
    return components;
  }
}
