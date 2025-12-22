import { ReactWidget } from "@jupyterlab/apputils";
import { NotebookPanel } from "@jupyterlab/notebook";
import { ITranslator } from "@jupyterlab/translation";
import React, { useEffect, useRef, useState } from "react";
import { requestAPI } from "./request";
import { calkitIcon } from "./icons";

/**
 * Badge dropdown component
 */
const BadgeDropdown: React.FC<{
  label: string;
  labelNode?: React.ReactNode;
  isConfigured?: boolean;
  isOpen: boolean;
  onToggle: () => void;
  onClose: () => void;
  buttonClassName?: string;
  children: React.ReactNode;
}> = ({
  label,
  labelNode,
  isConfigured = true,
  isOpen,
  onToggle,
  onClose,
  buttonClassName,
  children,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    const handleClickOutside = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        onClose();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen, onClose]);

  const buttonClasses = [
    "calkit-badge",
    isConfigured ? "" : "calkit-badge-unconfigured",
    buttonClassName || "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="calkit-badge-container" ref={containerRef}>
      <button
        className={buttonClasses}
        onClick={onToggle}
        title={isConfigured ? label : `${label} (not configured)`}
      >
        {labelNode || label}
      </button>
      {isOpen && <div className="calkit-badge-dropdown">{children}</div>}
    </div>
  );
};

/**
 * Environment badge component
 */
const EnvironmentBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [environments, setEnvironments] = useState<Record<string, any>>({});
  const [currentEnv, setCurrentEnv] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newEnvName, setNewEnvName] = useState("");
  const [newEnvLanguage, setNewEnvLanguage] = useState("python");
  const [newEnvVersion, setNewEnvVersion] = useState("");
  const [newEnvPackages, setNewEnvPackages] = useState("");

  // Fetch environments on mount
  useEffect(() => {
    const fetchEnvironments = async () => {
      try {
        const info = await requestAPI<any>("project");
        setEnvironments(info.environments || {});
        // Try to determine current environment from kernel name
        const kernelName = panel.sessionContext.session?.kernel?.name || "";
        const envNames = Object.keys(info.environments || {});
        // Simple heuristic: find environment that matches kernel name
        const matchedEnv = envNames.find((name) =>
          kernelName.toLowerCase().includes(name.toLowerCase()),
        );
        setCurrentEnv(matchedEnv || envNames[0] || "");
        setLoading(false);
      } catch (error) {
        console.error("Failed to fetch environments:", error);
        setLoading(false);
      }
    };

    fetchEnvironments();
  }, [panel]);

  const handleEnvironmentSelect = async (envName: string) => {
    setCurrentEnv(envName);
    setIsOpen(false);
    // TODO: Switch kernel to match environment
    console.log(`Switching to environment: ${envName}`);
  };

  const handleCreateNew = () => {
    setShowCreateForm(true);
  };

  const handleCancelCreate = () => {
    setShowCreateForm(false);
    setNewEnvName("");
    setNewEnvVersion("");
    setNewEnvPackages("");
  };

  const handleSubmitCreate = async () => {
    if (!newEnvName) {
      alert("Environment name is required");
      return;
    }

    try {
      const packages = newEnvPackages
        .split("\n")
        .map((p) => p.trim())
        .filter((p) => p.length > 0);

      await requestAPI("environment/create", {
        method: "POST",
        body: JSON.stringify({
          name: newEnvName,
          language: newEnvLanguage,
          version: newEnvVersion,
          packages: packages,
        }),
      });

      // Refresh environments
      const info = await requestAPI<any>("project");
      setEnvironments(info.environments || {});
      setCurrentEnv(newEnvName);
      setShowCreateForm(false);
      setNewEnvName("");
      setNewEnvVersion("");
      setNewEnvPackages("");
      setIsOpen(false);
    } catch (error) {
      console.error("Failed to create environment:", error);
      alert("Failed to create environment");
    }
  };

  const envNames = Object.keys(environments);
  const isConfigured = currentEnv !== "";
  const label = isConfigured ? `Env: ${currentEnv}` : "No environment selected";

  return (
    <BadgeDropdown
      label={label}
      isConfigured={isConfigured}
      isOpen={isOpen}
      onToggle={() => setIsOpen(!isOpen)}
      onClose={() => setIsOpen(false)}
    >
      {loading ? (
        <div className="calkit-dropdown-content">Loading...</div>
      ) : showCreateForm ? (
        <div className="calkit-dropdown-content">
          <h4>Create new environment</h4>
          <div className="calkit-form-group">
            <label>Name:</label>
            <input
              type="text"
              value={newEnvName}
              onChange={(e) => setNewEnvName(e.target.value)}
              placeholder="my-environment"
            />
          </div>
          <div className="calkit-form-group">
            <label>Language:</label>
            <select
              value={newEnvLanguage}
              onChange={(e) => setNewEnvLanguage(e.target.value)}
            >
              <option value="python">Python</option>
              <option value="julia">Julia</option>
              <option value="r">R</option>
              <option value="matlab">MATLAB</option>
            </select>
          </div>
          <div className="calkit-form-group">
            <label>Version:</label>
            <input
              type="text"
              value={newEnvVersion}
              onChange={(e) => setNewEnvVersion(e.target.value)}
              placeholder="e.g., 3.11"
            />
          </div>
          <div className="calkit-form-group">
            <label>Packages (one per line):</label>
            <textarea
              value={newEnvPackages}
              onChange={(e) => setNewEnvPackages(e.target.value)}
              placeholder="numpy&#10;pandas&#10;matplotlib"
              rows={5}
            />
          </div>
          <div className="calkit-form-actions">
            <button onClick={handleSubmitCreate}>Create</button>
            <button onClick={handleCancelCreate}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="calkit-dropdown-content">
          <div className="calkit-dropdown-section">
            <h4>Select environment</h4>
            {envNames.length === 0 ? (
              <p>No environments available</p>
            ) : (
              <div className="calkit-env-list">
                {envNames.map((name) => (
                  <div
                    key={name}
                    className={`calkit-env-item ${
                      name === currentEnv ? "calkit-env-item-active" : ""
                    }`}
                    onClick={() => handleEnvironmentSelect(name)}
                  >
                    {name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="calkit-dropdown-divider" />
          <button className="calkit-dropdown-button" onClick={handleCreateNew}>
            + Create New Environment
          </button>
        </div>
      )}
    </BadgeDropdown>
  );
};

/**
 * Pipeline stage badge component
 */
const PipelineStageBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [stages, setStages] = useState<string[]>([]);
  const [currentStage, setCurrentStage] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [newStageName, setNewStageName] = useState("");
  const [creating, setCreating] = useState(false);

  // Fetch pipeline stages on mount
  useEffect(() => {
    const fetchStages = async () => {
      try {
        const info = await requestAPI<any>("pipeline/stages");
        setStages(info.stages || []);
        // Try to get notebook's current stage
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebook/info?path=${encodeURIComponent(notebookPath)}`,
        );
        setCurrentStage(notebookInfo.stage || "");
        setLoading(false);
      } catch (error) {
        console.error("Failed to fetch pipeline stages:", error);
        setLoading(false);
      }
    };

    fetchStages();
  }, [panel]);

  const handleStageSelect = async (stage: string) => {
    setCurrentStage(stage);
    setIsOpen(false);
    const notebookPath = panel.context.path;
    try {
      await requestAPI("notebook/set-stage", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
          stage: stage,
        }),
      });
    } catch (error) {
      console.error("Failed to set pipeline stage:", error);
    }
  };

  const handleCreateStage = async () => {
    if (!newStageName.trim()) {
      return;
    }
    setCreating(true);
    const stage = newStageName.trim();
    const notebookPath = panel.context.path;
    try {
      await requestAPI("pipeline/create-stage", {
        method: "POST",
        body: JSON.stringify({
          stage,
          path: notebookPath,
        }),
      });
      setStages((prev) => Array.from(new Set([...prev, stage])));
      setCurrentStage(stage);
      setNewStageName("");
      setIsOpen(false);
    } catch (error) {
      console.error("Failed to create pipeline stage:", error);
    } finally {
      setCreating(false);
    }
  };

  const isConfigured = currentStage !== "";
  const label = isConfigured ? `Stage: ${currentStage}` : "Not in pipeline";

  return (
    <BadgeDropdown
      label={label}
      isConfigured={isConfigured}
      isOpen={isOpen}
      onToggle={() => setIsOpen(!isOpen)}
      onClose={() => setIsOpen(false)}
    >
      {loading ? (
        <div className="calkit-dropdown-content">Loading...</div>
      ) : (
        <div className="calkit-dropdown-content">
          <h4>Select pipeline stage</h4>
          {stages.length === 0 ? (
            <p>No stages available</p>
          ) : (
            <div className="calkit-stage-list">
              {stages.map((stage) => (
                <div
                  key={stage}
                  className={`calkit-stage-item ${
                    stage === currentStage ? "calkit-stage-item-active" : ""
                  }`}
                  onClick={() => handleStageSelect(stage)}
                >
                  {stage}
                </div>
              ))}
            </div>
          )}
          <div className="calkit-dropdown-divider" />
          <div className="calkit-form-group">
            <label>Add a new stage</label>
            <div className="calkit-input-row">
              <input
                type="text"
                value={newStageName}
                onChange={(e) => setNewStageName(e.target.value)}
                placeholder="e.g., postprocess"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleCreateStage();
                  }
                }}
              />
              <button onClick={handleCreateStage} disabled={creating}>
                {creating ? "Creating..." : "Add"}
              </button>
            </div>
          </div>
        </div>
      )}
    </BadgeDropdown>
  );
};

/**
 * Inputs badge component
 */
const InputsBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [inputs, setInputs] = useState<string[]>([]);
  const [manualInput, setManualInput] = useState("");

  // Load inputs on mount
  useEffect(() => {
    const loadInputs = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebook/info?path=${encodeURIComponent(notebookPath)}`,
        );
        setInputs(notebookInfo.inputs || []);
      } catch (error) {
        console.error("Failed to load inputs:", error);
      }
    };

    loadInputs();
  }, [panel]);

  const handleAutoDetect = async () => {
    try {
      const notebookPath = panel.context.path;
      const result = await requestAPI<any>("notebook/detect-inputs", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
        }),
      });
      setInputs(result.inputs || []);
    } catch (error) {
      console.error("Failed to auto-detect inputs:", error);
      alert("Failed to auto-detect inputs");
    }
  };

  const handleAddManual = () => {
    if (manualInput.trim()) {
      setInputs([...inputs, manualInput.trim()]);
      setManualInput("");
    }
  };

  const handleRemoveInput = (index: number) => {
    setInputs(inputs.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    try {
      const notebookPath = panel.context.path;
      await requestAPI("notebook/set-inputs", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
          inputs: inputs,
        }),
      });
      setIsOpen(false);
    } catch (error) {
      console.error("Failed to save inputs:", error);
      alert("Failed to save inputs");
    }
  };
  const label = `Inputs (${inputs.length})`;

  return (
    <BadgeDropdown
      label={label}
      isConfigured={true}
      buttonClassName="calkit-badge-gray"
      isOpen={isOpen}
      onToggle={() => setIsOpen(!isOpen)}
      onClose={() => setIsOpen(false)}
    >
      <div className="calkit-dropdown-content">
        <h4>Notebook inputs</h4>
        <button className="calkit-dropdown-button" onClick={handleAutoDetect}>
          🔍 Auto-Detect Inputs
        </button>
        <div className="calkit-io-list">
          {inputs.map((input, index) => (
            <div key={index} className="calkit-io-item">
              <span>{input}</span>
              <button
                className="calkit-io-remove"
                onClick={() => handleRemoveInput(index)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <div className="calkit-form-group">
          <label>Add manually:</label>
          <div className="calkit-input-row">
            <input
              type="text"
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder="path/to/input.csv"
              onKeyPress={(e) => {
                if (e.key === "Enter") {
                  handleAddManual();
                }
              }}
            />
            <button onClick={handleAddManual}>Add</button>
          </div>
        </div>
        <div className="calkit-form-actions">
          <button onClick={handleSave}>Save</button>
          <button onClick={() => setIsOpen(false)}>Close</button>
        </div>
      </div>
    </BadgeDropdown>
  );
};

/**
 * Outputs badge component
 */
const OutputsBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [outputs, setOutputs] = useState<string[]>([]);
  const [manualOutput, setManualOutput] = useState("");

  // Load outputs on mount
  useEffect(() => {
    const loadOutputs = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebook/info?path=${encodeURIComponent(notebookPath)}`,
        );
        setOutputs(notebookInfo.outputs || []);
      } catch (error) {
        console.error("Failed to load outputs:", error);
      }
    };

    loadOutputs();
  }, [panel]);

  const handleAutoDetect = async () => {
    try {
      const notebookPath = panel.context.path;
      const result = await requestAPI<any>("notebook/detect-outputs", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
        }),
      });
      setOutputs(result.outputs || []);
    } catch (error) {
      console.error("Failed to auto-detect outputs:", error);
      alert("Failed to auto-detect outputs");
    }
  };

  const handleAddManual = () => {
    if (manualOutput.trim()) {
      setOutputs([...outputs, manualOutput.trim()]);
      setManualOutput("");
    }
  };

  const handleRemoveOutput = (index: number) => {
    setOutputs(outputs.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    try {
      const notebookPath = panel.context.path;
      await requestAPI("notebook/set-outputs", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
          outputs: outputs,
        }),
      });
      setIsOpen(false);
    } catch (error) {
      console.error("Failed to save outputs:", error);
      alert("Failed to save outputs");
    }
  };
  const label = `Outputs (${outputs.length})`;

  return (
    <BadgeDropdown
      label={label}
      isConfigured={true}
      buttonClassName="calkit-badge-gray"
      isOpen={isOpen}
      onToggle={() => setIsOpen(!isOpen)}
      onClose={() => setIsOpen(false)}
    >
      <div className="calkit-dropdown-content">
        <h4>Notebook outputs</h4>
        <button className="calkit-dropdown-button" onClick={handleAutoDetect}>
          🔍 Auto-Detect Outputs
        </button>
        <div className="calkit-io-list">
          {outputs.map((output, index) => (
            <div key={index} className="calkit-io-item">
              <span>{output}</span>
              <button
                className="calkit-io-remove"
                onClick={() => handleRemoveOutput(index)}
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <div className="calkit-form-group">
          <label>Add manually:</label>
          <div className="calkit-input-row">
            <input
              type="text"
              value={manualOutput}
              onChange={(e) => setManualOutput(e.target.value)}
              placeholder="path/to/output.png"
              onKeyPress={(e) => {
                if (e.key === "Enter") {
                  handleAddManual();
                }
              }}
            />
            <button onClick={handleAddManual}>Add</button>
          </div>
        </div>
        <div className="calkit-form-actions">
          <button onClick={handleSave}>Save</button>
          <button onClick={() => setIsOpen(false)}>Close</button>
        </div>
      </div>
    </BadgeDropdown>
  );
};

/**
 * Info badge component
 */
const InfoBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  // Load notebook info on mount
  useEffect(() => {
    const loadInfo = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebook/info?path=${encodeURIComponent(notebookPath)}`,
        );
        setTitle(notebookInfo.title || "");
        setDescription(notebookInfo.description || "");
      } catch (error) {
        console.error("Failed to load notebook info:", error);
      }
    };

    loadInfo();
  }, [panel]);

  const handleSave = async () => {
    try {
      const notebookPath = panel.context.path;
      await requestAPI("notebook/set-info", {
        method: "POST",
        body: JSON.stringify({
          path: notebookPath,
          title: title,
          description: description,
        }),
      });
      setIsOpen(false);
    } catch (error) {
      console.error("Failed to save notebook info:", error);
      alert("Failed to save notebook info");
    }
  };

  return (
    <BadgeDropdown
      label="Info"
      labelNode={<calkitIcon.react height={14} />}
      isConfigured={true}
      buttonClassName="calkit-badge-icon"
      isOpen={isOpen}
      onToggle={() => setIsOpen(!isOpen)}
      onClose={() => setIsOpen(false)}
    >
      <div className="calkit-dropdown-content">
        <h4>Notebook information</h4>
        <div className="calkit-form-group">
          <label>Title:</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Notebook title"
          />
        </div>
        <div className="calkit-form-group">
          <label>Description:</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this notebook does..."
            rows={5}
          />
        </div>
        <div className="calkit-form-actions">
          <button onClick={handleSave}>Save</button>
          <button onClick={() => setIsOpen(false)}>Close</button>
        </div>
      </div>
    </BadgeDropdown>
  );
};

/**
 * Main notebook toolbar component
 */
const NotebookToolbar: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel, translator }) => {
  return (
    <div className="calkit-notebook-toolbar">
      <EnvironmentBadge panel={panel} translator={translator} />
      <PipelineStageBadge panel={panel} translator={translator} />
      <InputsBadge panel={panel} translator={translator} />
      <OutputsBadge panel={panel} translator={translator} />
      <InfoBadge panel={panel} translator={translator} />
    </div>
  );
};

/**
 * Widget wrapper for the notebook toolbar
 */
export class NotebookToolbarWidget extends ReactWidget {
  constructor(
    private panel: NotebookPanel,
    private translator?: ITranslator,
  ) {
    super();
    this.addClass("calkit-notebook-toolbar-widget");
  }

  render() {
    return <NotebookToolbar panel={this.panel} translator={this.translator} />;
  }
}

/**
 * Create notebook toolbar for notebook toolbar
 */
export function createNotebookToolbar(
  panel: NotebookPanel,
  translator?: ITranslator,
): NotebookToolbarWidget {
  return new NotebookToolbarWidget(panel, translator);
}
