import React, { useState } from "react";
import { Dialog } from "@jupyterlab/apputils";
import { ReactWidget } from "@jupyterlab/apputils";

/**
 * Props for the project info editor dialog body
 */
interface ProjectInfoEditorProps {
  name: string;
  title: string;
  description: string;
  git_repo_url: string;
  owner: string;
}

/**
 * The body component for the project info editor dialog
 */
const ProjectInfoEditorBody: React.FC<
  ProjectInfoEditorProps & {
    onUpdate: (data: ProjectInfoEditorProps) => void;
  }
> = ({ name, title, description, git_repo_url, owner, onUpdate }) => {
  const [nameValue, setNameValue] = useState(name);
  const [titleValue, setTitleValue] = useState(title);
  const [descriptionValue, setDescriptionValue] = useState(description);
  const [gitRepoUrlValue, setGitRepoUrlValue] = useState(git_repo_url);
  const [ownerValue, setOwnerValue] = useState(owner);
  const [advancedExpanded, setAdvancedExpanded] = useState(false);

  React.useEffect(() => {
    onUpdate({
      name: nameValue,
      title: titleValue,
      description: descriptionValue,
      git_repo_url: gitRepoUrlValue,
      owner: ownerValue,
    });
  }, [
    nameValue,
    titleValue,
    descriptionValue,
    gitRepoUrlValue,
    ownerValue,
    onUpdate,
  ]);

  return (
    <div className="calkit-project-info-editor">
      <div className="calkit-dialog-field">
        <label htmlFor="project-name">Project name:</label>
        <input
          id="project-name"
          type="text"
          value={nameValue}
          onChange={(e) => setNameValue(e.target.value)}
          placeholder="my-project"
          autoFocus
        />
        <small>Use kebab-case (e.g., my-awesome-project)</small>
      </div>
      <div className="calkit-dialog-field">
        <label htmlFor="project-title">Title:</label>
        <input
          id="project-title"
          type="text"
          value={titleValue}
          onChange={(e) => setTitleValue(e.target.value)}
          placeholder="My Awesome Project"
        />
      </div>
      <div className="calkit-dialog-field">
        <label htmlFor="project-description">Description:</label>
        <textarea
          id="project-description"
          value={descriptionValue}
          onChange={(e) => setDescriptionValue(e.target.value)}
          placeholder="A brief description of the project..."
          rows={4}
        />
      </div>

      {/* Advanced Section */}
      <div className="calkit-project-info-advanced">
        <button
          className="calkit-project-info-advanced-toggle"
          type="button"
          onClick={() => setAdvancedExpanded(!advancedExpanded)}
        >
          <span
            className={`calkit-project-info-chevron ${
              advancedExpanded ? "expanded" : ""
            }`}
          >
            ▼
          </span>
          Advanced
        </button>

        {advancedExpanded && (
          <div className="calkit-project-info-advanced-fields">
            <div className="calkit-dialog-field">
              <label htmlFor="project-owner">Owner:</label>
              <input
                id="project-owner"
                type="text"
                value={ownerValue}
                onChange={(e) => setOwnerValue(e.target.value)}
                placeholder="username or organization"
              />
            </div>
            <div className="calkit-dialog-field">
              <label htmlFor="project-git-url">Git repo URL:</label>
              <input
                id="project-git-url"
                type="text"
                value={gitRepoUrlValue}
                onChange={(e) => setGitRepoUrlValue(e.target.value)}
                placeholder="https://github.com/user/repo"
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

/**
 * A ReactWidget that wraps the project info editor dialog body
 */
class ProjectInfoEditorWidget extends ReactWidget {
  private _data: ProjectInfoEditorProps;

  constructor(private options: ProjectInfoEditorProps) {
    super();
    this._data = { ...options };
  }

  render(): JSX.Element {
    return (
      <ProjectInfoEditorBody
        {...this.options}
        onUpdate={(data) => {
          this._data = data;
        }}
      />
    );
  }

  getValue(): ProjectInfoEditorProps {
    return this._data;
  }
}

/**
 * Show a dialog to edit project info
 */
export async function showProjectInfoEditor(
  options: ProjectInfoEditorProps,
): Promise<ProjectInfoEditorProps | null> {
  const widget = new ProjectInfoEditorWidget(options);

  const dialog = new Dialog({
    title: "Edit Project Info",
    body: widget,
    buttons: [Dialog.cancelButton(), Dialog.okButton({ label: "Save" })],
  });

  const result = await dialog.launch();
  if (result.button.accept) {
    return widget.getValue();
  }
  return null;
}
