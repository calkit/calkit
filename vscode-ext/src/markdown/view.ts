import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

import type { CalkitInfo } from "../types";
import {
  STAGE_NAME_SEPARATOR,
  findMarkdownStageBlocks,
  findProjectDir,
  markdownStageNameForFile,
} from "./core";

export interface MarkdownStageCodeLensDeps {
  getWorkspaceRoot: () => string | undefined;
  readCalkitConfig: (projectDir: string) => Promise<CalkitInfo | undefined>;
  runMarkdownStageCommand: string;
}

/** Where a Markdown file's project is, and what the file is called in it. */
export function resolveMarkdownProject(
  fsPath: string,
  workspaceRoot: string,
): { projectDir: string; relPath: string } | undefined {
  const projectDir = findProjectDir(fsPath, workspaceRoot, fs.existsSync, path);
  if (!projectDir) {
    return undefined;
  }
  return {
    projectDir,
    relPath: path.relative(projectDir, fsPath).replace(/\\/g, "/"),
  };
}

/** Puts a "Run stage" action above each stage declared in a Markdown file. */
export class MarkdownStageCodeLensProvider implements vscode.CodeLensProvider {
  private readonly _onDidChangeCodeLenses = new vscode.EventEmitter<void>();
  readonly onDidChangeCodeLenses = this._onDidChangeCodeLenses.event;

  constructor(private readonly deps: MarkdownStageCodeLensDeps) {}

  refresh(): void {
    this._onDidChangeCodeLenses.fire();
  }

  async provideCodeLenses(
    document: vscode.TextDocument,
  ): Promise<vscode.CodeLens[]> {
    const workspaceRoot = this.deps.getWorkspaceRoot();
    if (!workspaceRoot) {
      return [];
    }
    const project = resolveMarkdownProject(document.uri.fsPath, workspaceRoot);
    if (!project) {
      return [];
    }
    const config = await this.deps.readCalkitConfig(project.projectDir);
    // Only files the pipeline actually sources its stages from; an ordinary
    // Markdown file that happens to contain an annotation is not one.
    const mdStageName = markdownStageNameForFile(config, project.relPath);
    if (!mdStageName) {
      return [];
    }
    return findMarkdownStageBlocks(document.getText()).map((block) => {
      const stageName = mdStageName + STAGE_NAME_SEPARATOR + block.name;
      return new vscode.CodeLens(
        new vscode.Range(block.line, 0, block.line, 0),
        {
          title: `$(play) Run stage: ${block.name}`,
          command: this.deps.runMarkdownStageCommand,
          arguments: [stageName, project.projectDir],
        },
      );
    });
  }
}
