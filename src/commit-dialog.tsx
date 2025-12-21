import React, { useState } from "react";
import { Dialog } from "@jupyterlab/apputils";
import { ReactWidget } from "@jupyterlab/apputils";

interface CommitFile {
  path: string;
  stage: boolean;
  store_in_dvc?: boolean;
  tracked?: boolean;
  size?: number;
  ignore_forever?: boolean;
}

interface CommitDialogProps {
  defaultMessage: string;
  files: CommitFile[];
  onUpdate: (data: {
    message: string;
    files: CommitFile[];
    pushAfter?: boolean;
  }) => void;
}

const CommitDialogBody: React.FC<CommitDialogProps> = ({
  defaultMessage,
  files,
  onUpdate,
}) => {
  const [message, setMessage] = useState(defaultMessage);
  const [fileSelections, setFileSelections] = useState<CommitFile[]>(files);
  const [pushAfter, setPushAfter] = useState(false);

  React.useEffect(() => {
    onUpdate({ message, files: fileSelections, pushAfter });
  }, [message, fileSelections, pushAfter, onUpdate]);

  const setChoice = (
    path: string,
    choice: "git" | "dvc" | "ignore" | "ignore_forever",
    tracked?: boolean,
  ) => {
    setFileSelections((prev) =>
      prev.map((f) => {
        if (f.path !== path) return f;
        if (choice === "git") {
          return {
            ...f,
            stage: true,
            store_in_dvc: false,
            ignore_forever: false,
          };
        }
        if (choice === "dvc") {
          return {
            ...f,
            stage: true,
            store_in_dvc: true,
            ignore_forever: false,
          };
        }
        if (choice === "ignore_forever") {
          return {
            ...f,
            stage: false,
            store_in_dvc: false,
            ignore_forever: true,
          };
        }
        return {
          ...f,
          stage: false,
          store_in_dvc: false,
          ignore_forever: false,
        };
      }),
    );
  };

  const stagedCount = fileSelections.filter((f) => f.stage).length;

  return (
    <div className="calkit-project-info-editor">
      <div className="calkit-dialog-field">
        <label htmlFor="commit-message">Commit message</label>
        <textarea
          id="commit-message"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Describe your changes"
        />
      </div>
      <div className="calkit-dialog-field">
        <label>Files to include ({stagedCount} selected)</label>
        <div className="calkit-commit-file-list">
          <div className="calkit-commit-file-header">
            <span className="calkit-commit-col-path">File</span>
            <span className="calkit-commit-col-choice" title="Save with Git">
              Git
            </span>
            <span className="calkit-commit-col-choice" title="Store in DVC">
              DVC
            </span>
            <span className="calkit-commit-col-choice" title="Skip this time">
              Ignore
            </span>
            <span
              className="calkit-commit-col-choice"
              title="Add to .gitignore"
            >
              Ignore forever
            </span>
          </div>
          {fileSelections.length === 0 ? (
            <div className="calkit-commit-file-empty">No files selected</div>
          ) : (
            fileSelections.map((f) => (
              <div key={f.path} className="calkit-commit-file-row">
                <span className="calkit-commit-file-path" title={f.path}>
                  {f.path}
                </span>
                <label className="calkit-commit-file-choice">
                  <input
                    type="radio"
                    name={`choice-${f.path}`}
                    checked={f.stage && !f.store_in_dvc}
                    onChange={() => setChoice(f.path, "git", f.tracked)}
                  />
                </label>
                <label className="calkit-commit-file-choice">
                  <input
                    type="radio"
                    name={`choice-${f.path}`}
                    disabled={!!f.tracked}
                    checked={f.stage && !!f.store_in_dvc}
                    onChange={() => setChoice(f.path, "dvc", f.tracked)}
                  />
                </label>
                <label className="calkit-commit-file-choice">
                  <input
                    type="radio"
                    name={`choice-${f.path}`}
                    checked={!f.stage && !f.ignore_forever}
                    onChange={() => setChoice(f.path, "ignore", f.tracked)}
                  />
                </label>
                <label className="calkit-commit-file-choice">
                  <input
                    type="radio"
                    name={`choice-${f.path}`}
                    checked={!!f.ignore_forever}
                    onChange={() =>
                      setChoice(f.path, "ignore_forever", f.tracked)
                    }
                  />
                </label>
              </div>
            ))
          )}
        </div>
      </div>
      <div className="calkit-dialog-field calkit-commit-push-toggle">
        <label className="calkit-checkbox-label">
          <input
            type="checkbox"
            className="calkit-dialog-checkbox"
            checked={pushAfter}
            onChange={(e) => setPushAfter(e.target.checked)}
          />
          Push after commit
        </label>
      </div>
    </div>
  );
};

class CommitDialogWidget extends ReactWidget {
  private data: { message: string; files: CommitFile[] } = {
    message: "",
    files: [],
  };
  constructor(private props: CommitDialogProps) {
    super();
    this.addClass("calkit-commit-dialog");
  }
  render(): React.ReactElement<any> {
    return (
      <CommitDialogBody
        defaultMessage={this.props.defaultMessage}
        files={this.props.files}
        onUpdate={(d) => (this.data = d)}
      />
    );
  }
  getData() {
    return this.data;
  }
}

export async function showCommitDialog(
  defaultMessage: string,
  files: CommitFile[],
): Promise<{
  message: string;
  files: CommitFile[];
  pushAfter?: boolean;
} | null> {
  const body = new CommitDialogWidget({
    defaultMessage,
    files,
    onUpdate: () => {},
  });
  const result = await new Dialog<{
    message: string;
    files: CommitFile[];
    pushAfter?: boolean;
  }>({
    title: "Save changes",
    body,
    buttons: [Dialog.cancelButton(), Dialog.okButton({ label: "Commit" })],
  }).launch();
  if (result.button.accept) {
    const data = body.getData();
    const staged = data.files.filter((f) => f.stage);
    if (staged.length === 0) {
      return null;
    }
    return data;
  }
  return null;
}
