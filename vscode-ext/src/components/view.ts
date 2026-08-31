import * as vscode from "vscode";
import {
  componentsByLine,
  figureComponent,
  definitionLine,
  hoverLines,
  isLatexDocument,
  lensTitle,
  toAbsolute,
  withCheckedStatus,
} from "./core";
import type { Component, DocumentComponents } from "./core";
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
      if (component.stage) {
        const args = encodeURIComponent(JSON.stringify([component.stage]));
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
      const title = lensTitle(onLine);
      if (title === undefined || line >= document.lineCount) {
        continue;
      }
      // Running the stage is the action worth one keystroke; without one
      // there is nothing to run, so the lens just reports
      const stage = onLine.find((c) => c.status !== "ok" && c.stage)?.stage;
      lenses.push(
        new vscode.CodeLens(new vscode.Range(line, 0, line, 0), {
          title,
          command: stage ? this.deps.runStageCommand : "",
          arguments: stage ? [stage] : undefined,
        }),
      );
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
