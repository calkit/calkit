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
  const [userEditedName, setUserEditedName] = useState(false);

  // Auto-update name when title changes (if user hasn't manually edited name)
  React.useEffect(() => {
    if (!userEditedName && titleValue) {
      const kebabCaseName = titleValue
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^a-z0-9-]/g, "")
        .replace(/-+/g, "-")
        .replace(/^-|-$/g, "");
      setNameValue(kebabCaseName);
    }
  }, [titleValue, userEditedName]);

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
        <label htmlFor="project-title">Title:</label>
        <input
          id="project-title"
          type="text"
          value={titleValue}
          onChange={(e) => setTitleValue(e.target.value)}
          placeholder="My Awesome Project"
          autoFocus
        />
      </div>
      <div className="calkit-dialog-field">
        <label htmlFor="project-description">Description:</label>
        <textarea
          id="project-description"
          value={descriptionValue}
          onChange={(e) => setDescriptionValue(e.target.value)}
          placeholder="ex: A project about awesome things."
          rows={4}
        />
      </div>
      <div className="calkit-dialog-field">
        <label htmlFor="project-name">Name:</label>
        <input
          id="project-name"
          type="text"
          value={nameValue}
          onChange={(e) => {
            setNameValue(e.target.value);
            setUserEditedName(true);
          }}
          placeholder="ex: my-awesome-project"
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
  private data: ProjectInfoEditorProps;

  constructor(options: ProjectInfoEditorProps) {
    super();
    this.data = { ...options };
    this.addClass("calkit-project-info-dialog");
  }

  render(): React.ReactElement<any> {
    return (
      <ProjectInfoEditorBody
        {...this.data}
        onUpdate={(data) => {
          this.data = data;
        }}
      />
    );
  }

  getData(): ProjectInfoEditorProps {
    return this.data;
  }
}

/**
 * Show a dialog to edit project info
 * @param options The project info to edit
 * @param isInitialSetup Whether this is the initial project setup (affects title)
 */
export async function showProjectInfoEditor(
  options: ProjectInfoEditorProps,
  isInitialSetup: boolean = false,
): Promise<ProjectInfoEditorProps | null> {
  console.log(
    "showProjectInfoEditor called with options:",
    options,
    "isInitialSetup:",
    isInitialSetup,
  );

  const body = new ProjectInfoEditorWidget(options);
  console.log("ProjectInfoEditorWidget created");

  const dialog = new Dialog<ProjectInfoEditorProps>({
    title: "Set project info",
    body,
    buttons: [Dialog.cancelButton(), Dialog.okButton({ label: "Save" })],
  });

  console.log("Dialog created, about to launch...");

  const result = await dialog.launch();

  console.log("Dialog launch completed, result:", result);

  if (result.button.accept) {
    console.log("User accepted, getting data from widget...");
    const data = body.getData();
    console.log("Data from widget:", data);
    return data;
  }

  console.log("User cancelled or rejected");
  return null;
}
