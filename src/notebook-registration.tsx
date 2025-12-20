import React, { useState } from "react";
import { ReactWidget, Dialog } from "@jupyterlab/apputils";

interface NotebookData {
  path: string;
  title?: string;
  description?: string;
  environment?: string;
  inPipeline?: boolean;
  inputs?: string[];
  outputs?: string[];
}

interface NotebookRegistrationBodyProps {
  mode: "create" | "register";
  existingNotebooks?: string[];
  availableEnvironments?: Array<{ id: string; label: string }>;
  onCreateEnvironment?: () => Promise<string | null>;
}

const NotebookRegistrationBody: React.FC<NotebookRegistrationBodyProps> = ({
  mode,
  existingNotebooks = [],
  availableEnvironments = [],
  onCreateEnvironment,
}) => {
  const [notebookPath, setNotebookPath] = useState("");
  const [selectedNotebook, setSelectedNotebook] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [environment, setEnvironment] = useState("");
  const [inPipeline, setInPipeline] = useState(true);
  const [inputs, setInputs] = useState<string[]>([]);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [newInput, setNewInput] = useState("");
  const [newOutput, setNewOutput] = useState("");

  const addInput = () => {
    if (newInput.trim()) {
      setInputs([...inputs, newInput.trim()]);
      setNewInput("");
    }
  };

  const removeInput = (index: number) => {
    setInputs(inputs.filter((_, i) => i !== index));
  };

  const addOutput = () => {
    if (newOutput.trim()) {
      setOutputs([...outputs, newOutput.trim()]);
      setNewOutput("");
    }
  };

  const removeOutput = (index: number) => {
    setOutputs(outputs.filter((_, i) => i !== index));
  };

  return (
    <div className="calkit-notebook-registration">
      {mode === "create" ? (
        <>
          <p className="calkit-dialog-description">
            Create a new Jupyter notebook and register it with Calkit.
          </p>
          <div className="calkit-dialog-field">
            <label htmlFor="notebook-path">Notebook path:</label>
            <input
              id="notebook-path"
              type="text"
              placeholder="e.g., analysis.ipynb"
              value={notebookPath}
              onChange={(e) => setNotebookPath(e.target.value)}
              className="calkit-dialog-input"
            />
          </div>
          <div className="calkit-dialog-field">
            <label htmlFor="notebook-title">Title (optional):</label>
            <input
              id="notebook-title"
              type="text"
              placeholder="Descriptive title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="calkit-dialog-input"
            />
          </div>
          <div className="calkit-dialog-field">
            <label htmlFor="notebook-description">
              Description (optional):
            </label>
            <textarea
              id="notebook-description"
              placeholder="Brief description of what this notebook does"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="calkit-dialog-textarea"
              rows={3}
            />
          </div>
          <div className="calkit-dialog-field">
            <label htmlFor="notebook-environment">
              Environment (optional):
            </label>
            <select
              id="notebook-environment"
              value={environment}
              onChange={async (e) => {
                const value = e.target.value;
                if (value === "__create_new__" && onCreateEnvironment) {
                  const newEnvName = await onCreateEnvironment();
                  if (newEnvName) {
                    setEnvironment(newEnvName);
                  }
                } else {
                  setEnvironment(value);
                }
              }}
              className="calkit-dialog-select"
            >
              <option value="">None</option>
              {availableEnvironments.map((env) => (
                <option key={env.id} value={env.id}>
                  {env.label}
                </option>
              ))}
              <option value="__create_new__">+ Create New Environment</option>
            </select>
          </div>
          <div className="calkit-dialog-field">
            <label className="calkit-checkbox-label">
              <input
                id="notebook-in-pipeline"
                type="checkbox"
                checked={inPipeline}
                onChange={(e) => setInPipeline(e.target.checked)}
                className="calkit-dialog-checkbox"
              />
              Include in pipeline
            </label>
          </div>
          <div className="calkit-dialog-field">
            <label>Input paths (optional):</label>
            <div className="calkit-path-list">
              {inputs.map((input, idx) => (
                <div key={idx} className="calkit-path-item">
                  <span className="calkit-path-text">{input}</span>
                  <button
                    className="calkit-path-remove"
                    onClick={() => removeInput(idx)}
                    type="button"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <div className="calkit-path-add">
              <input
                id="notebook-new-input"
                type="text"
                placeholder="Add input path..."
                value={newInput}
                onChange={(e) => setNewInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addInput();
                  }
                }}
                className="calkit-dialog-input"
              />
              <button
                onClick={addInput}
                disabled={!newInput.trim()}
                className="calkit-path-add-button"
                type="button"
              >
                +
              </button>
            </div>
          </div>
          <div className="calkit-dialog-field">
            <label>Output paths (optional):</label>
            <div className="calkit-path-list">
              {outputs.map((output, idx) => (
                <div key={idx} className="calkit-path-item">
                  <span className="calkit-path-text">{output}</span>
                  <button
                    className="calkit-path-remove"
                    onClick={() => removeOutput(idx)}
                    type="button"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            <div className="calkit-path-add">
              <input
                id="notebook-new-output"
                type="text"
                placeholder="Add output path..."
                value={newOutput}
                onChange={(e) => setNewOutput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addOutput();
                  }
                }}
                className="calkit-dialog-input"
              />
              <button
                onClick={addOutput}
                disabled={!newOutput.trim()}
                className="calkit-path-add-button"
                type="button"
              >
                +
              </button>
            </div>
          </div>
        </>
      ) : (
        <>
          <p className="calkit-dialog-description">
            Register an existing notebook with Calkit.
          </p>
          <div className="calkit-dialog-field">
            <label htmlFor="notebook-select">Select notebook:</label>
            <select
              id="notebook-select"
              value={selectedNotebook}
              onChange={(e) => setSelectedNotebook(e.target.value)}
              className="calkit-dialog-select"
            >
              <option value="">Choose a notebook...</option>
              {existingNotebooks.map((nb) => (
                <option key={nb} value={nb}>
                  {nb}
                </option>
              ))}
            </select>
          </div>
        </>
      )}
    </div>
  );
};

class NotebookRegistrationWidget extends ReactWidget {
  private mode: "create" | "register";
  private existingNotebooks: string[];
  private availableEnvironments: Array<{ id: string; label: string }>;
  private onCreateEnvironment?: () => Promise<string | null>;

  constructor(
    mode: "create" | "register",
    existingNotebooks: string[] = [],
    availableEnvironments: Array<{ id: string; label: string }> = [],
    onCreateEnvironment?: () => Promise<string | null>,
  ) {
    super();
    this.mode = mode;
    this.existingNotebooks = existingNotebooks;
    this.availableEnvironments = availableEnvironments;
    this.onCreateEnvironment = onCreateEnvironment;
  }

  render(): JSX.Element {
    return (
      <NotebookRegistrationBody
        mode={this.mode}
        existingNotebooks={this.existingNotebooks}
        availableEnvironments={this.availableEnvironments}
        onCreateEnvironment={this.onCreateEnvironment}
      />
    );
  }

  getValue(): NotebookData | null {
    if (this.mode === "create") {
      const pathInput =
        this.node.querySelector<HTMLInputElement>("#notebook-path");
      const titleInput =
        this.node.querySelector<HTMLInputElement>("#notebook-title");
      const descInput = this.node.querySelector<HTMLTextAreaElement>(
        "#notebook-description",
      );
      const envSelect = this.node.querySelector<HTMLSelectElement>(
        "#notebook-environment",
      );
      const pipelineCheck = this.node.querySelector<HTMLInputElement>(
        "#notebook-in-pipeline",
      );

      const path = pathInput?.value || "";
      if (!path.trim()) {
        return null;
      }

      // Collect inputs
      const inputs: string[] = [];
      this.node.querySelectorAll(".calkit-path-item").forEach((item, idx) => {
        const parent = item.closest(".calkit-dialog-field");
        const label = parent?.querySelector("label")?.textContent || "";
        if (label.includes("Input")) {
          const text = item.querySelector(".calkit-path-text")?.textContent;
          if (text) inputs.push(text);
        }
      });

      // Collect outputs
      const outputs: string[] = [];
      this.node.querySelectorAll(".calkit-path-item").forEach((item, idx) => {
        const parent = item.closest(".calkit-dialog-field");
        const label = parent?.querySelector("label")?.textContent || "";
        if (label.includes("Output")) {
          const text = item.querySelector(".calkit-path-text")?.textContent;
          if (text) outputs.push(text);
        }
      });

      return {
        path: path.trim(),
        title: titleInput?.value.trim() || undefined,
        description: descInput?.value.trim() || undefined,
        environment: envSelect?.value || undefined,
        inPipeline: pipelineCheck?.checked || false,
        inputs: inputs.length > 0 ? inputs : undefined,
        outputs: outputs.length > 0 ? outputs : undefined,
      };
    } else {
      const select =
        this.node.querySelector<HTMLSelectElement>("#notebook-select");
      const path = select?.value || "";
      return path.trim() ? { path: path.trim() } : null;
    }
  }
}

export async function showNotebookRegistration(
  mode: "create" | "register",
  existingNotebooks: string[] = [],
  availableEnvironments: Array<{ id: string; label: string }> = [],
  onCreateEnvironment?: () => Promise<string | null>,
): Promise<NotebookData | null> {
  const widget = new NotebookRegistrationWidget(
    mode,
    existingNotebooks,
    availableEnvironments,
    onCreateEnvironment,
  );
  const title =
    mode === "create" ? "Create New Notebook" : "Register Existing Notebook";

  const dialog = new Dialog({
    title,
    body: widget,
    buttons: [
      Dialog.cancelButton(),
      Dialog.okButton({ label: mode === "create" ? "Create" : "Register" }),
    ],
  });

  const result = await dialog.launch();
  if (!result.button.accept) {
    return null;
  }

  return widget.getValue();
}
