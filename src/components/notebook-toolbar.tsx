import { ReactWidget, showErrorMessage } from "@jupyterlab/apputils";
import { NotebookPanel, NotebookActions } from "@jupyterlab/notebook";
import { ITranslator } from "@jupyterlab/translation";
import React, { useEffect, useRef, useState } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { requestAPI } from "../request";
import { queryClient } from "../queryClient";
import { calkitIcon } from "../icons";
import { showEnvironmentEditor } from "./environment-editor";
import { usePipelineStatus, useSetNotebookStage } from "../hooks/useQueries";

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
  const [switchingKernel, setSwitchingKernel] = useState(false);

  const switchKernelForEnvironment = async (envName: string) => {
    if (!envName) {
      return;
    }
    const notebookPath = panel.context.path;
    setSwitchingKernel(true);
    try {
      const res = await requestAPI<any>("notebook/kernel", {
        method: "POST",
        body: JSON.stringify({ path: notebookPath, environment: envName }),
      });
      const kernelName = res.kernel_name || res.name || envName;
      await panel.sessionContext.changeKernel({ name: kernelName });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to switch kernel:", error);
      await showErrorMessage(
        "Failed to switch kernel for environment",
        errorMsg,
      );
    } finally {
      setSwitchingKernel(false);
    }
  };

  const refreshEnvironments = async () => {
    const data = await requestAPI<any>("environments?notebook_only=1");
    setEnvironments(data.environments || {});

    // Fetch the notebook's specific environment
    const notebookPath = panel.context.path;
    try {
      const nbEnvData = await requestAPI<any>(
        `notebooks?path=${encodeURIComponent(notebookPath)}`,
      );
      if (nbEnvData.environment?.name) {
        setCurrentEnv(nbEnvData.environment.name);
        // Ensure kernel matches environment when opening notebook
        await switchKernelForEnvironment(nbEnvData.environment.name);
        return;
      }
    } catch (error) {
      console.warn("Failed to fetch notebook environment:", error);
    }

    // No environment explicitly set for this notebook; reflect as unconfigured
    setCurrentEnv("");
  };

  // Fetch environments on mount
  useEffect(() => {
    const fetchEnvironments = async () => {
      try {
        await refreshEnvironments();
        setLoading(false);
      } catch (error) {
        console.error("Failed to fetch environments:", error);
        setLoading(false);
      }
    };

    fetchEnvironments();
  }, [panel]);

  const handleEnvironmentSelect = async (envName: string) => {
    const notebookPath = panel.context.path;
    console.log(`Setting environment for ${notebookPath} to ${envName}`);
    try {
      console.log("Calling PUT notebook/environment");
      const envResponse = await requestAPI("notebook/environment", {
        method: "PUT",
        body: JSON.stringify({ path: notebookPath, environment: envName }),
      });
      console.log("Environment set response:", envResponse);
      setCurrentEnv(envName);
      await switchKernelForEnvironment(envName);
      // Invalidate queries so other UI reflects the change
      void queryClient.invalidateQueries({ queryKey: ["project"] });
      void queryClient.invalidateQueries({ queryKey: ["notebooks"] });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to set notebook environment:", error);
      await showErrorMessage("Failed to set notebook environment", errorMsg);
    } finally {
      setIsOpen(false);
    }
  };

  const handleCreateEnvironment = async () => {
    await showEnvironmentEditor({
      mode: "create",
      onSubmit: async ({ name, kind, path, packages }) => {
        await requestAPI("environments", {
          method: "POST",
          body: JSON.stringify({ name, kind, path, packages }),
        });
        await refreshEnvironments();
        setCurrentEnv(name);
        setIsOpen(false);
      },
    });
  };

  const handleEditEnvironment = async () => {
    if (!currentEnv) {
      return;
    }
    const envData = environments[currentEnv] || {};
    await showEnvironmentEditor({
      mode: "edit",
      initialName: currentEnv,
      initialKind: envData.kind || "uv-venv",
      initialPath: envData.path,
      initialPackages: envData.packages || [],
      onSubmit: async ({ name, kind, path, packages }) => {
        await requestAPI("environments", {
          method: "POST",
          body: JSON.stringify({ name, kind, path, packages }),
        });
        await refreshEnvironments();
        setCurrentEnv(name);
        setIsOpen(false);
      },
    });
  };

  const envNames = Object.keys(environments);
  const isConfigured = currentEnv !== "";
  const label = isConfigured
    ? `Environment: ${currentEnv}`
    : "No environment selected";

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
          <div className="calkit-dropdown-section">
            <h4>Select environment</h4>
            {switchingKernel && (
              <p className="calkit-note">Switching kernel, please wait…</p>
            )}
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
                    onClick={() => {
                      if (!switchingKernel) {
                        void handleEnvironmentSelect(name);
                      }
                    }}
                  >
                    {name}
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="calkit-dropdown-divider" />
          <div className="calkit-dropdown-actions">
            <button
              className="calkit-dropdown-button"
              onClick={handleCreateEnvironment}
            >
              Create new environment
            </button>
            <button
              className="calkit-dropdown-button"
              onClick={handleEditEnvironment}
              disabled={!currentEnv}
            >
              Edit current environment
            </button>
          </div>
        </div>
      )}
    </BadgeDropdown>
  );
};

/**
 * Inputs badge component
 */
const PipelineStageBadge: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [currentStage, setCurrentStage] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [stageName, setStageName] = useState("");
  const [currentEnv, setCurrentEnv] = useState<string>("");
  const [isStale, setIsStale] = useState(false);
  const { data: pipelineStatus } = usePipelineStatus();
  const setNotebookStageMutation = useSetNotebookStage();

  const waitForKernelIdle = async (kernel: any) => {
    if (!kernel) return;
    if (kernel.status === "idle") return;
    await new Promise<void>((resolve) => {
      const onStatusChange = (_: any, status: any) => {
        if (status === "idle") {
          kernel.statusChanged.disconnect(onStatusChange);
          clearTimeout(timeout);
          resolve();
        }
      };
      const timeout = setTimeout(() => {
        kernel.statusChanged.disconnect(onStatusChange);
        resolve();
      }, 5000);
      kernel.statusChanged.connect(onStatusChange);
    });
  };

  // Fetch notebook stage on mount
  useEffect(() => {
    const fetchStage = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebooks?path=${encodeURIComponent(notebookPath)}`,
        );
        const stage = notebookInfo.stage?.name || "";
        const env = notebookInfo.environment?.name || "";
        const stale = notebookInfo.stage?.is_stale || false;
        setCurrentStage(stage);
        setIsStale(stale);

        // If no stage is set, generate a default name from the notebook filename
        if (!stage) {
          const filename = notebookPath.split("/").pop() || "";
          const nameWithoutExt = filename.replace(/\.ipynb$/, "");
          const generatedStageName = `${nameWithoutExt}-notebook`;
          setStageName(generatedStageName);
        } else {
          setStageName(stage);
        }

        setCurrentEnv(env);
        setLoading(false);
      } catch (error) {
        console.error("Failed to fetch pipeline stages:", error);
        setLoading(false);
      }
    };

    fetchStage();
  }, [panel]);

  useEffect(() => {
    if (!pipelineStatus || !currentStage) {
      return;
    }

    const staleStages = pipelineStatus.stale_stages;
    if (staleStages && typeof staleStages === "object") {
      setIsStale(Boolean(staleStages[currentStage]));
      return;
    }

    const stageInfo = pipelineStatus.pipeline?.stages?.[currentStage];
    if (stageInfo) {
      const stageStale =
        stageInfo.is_stale ||
        stageInfo.is_outdated ||
        stageInfo.outdated ||
        stageInfo.needs_run;
      setIsStale(Boolean(stageStale));
    } else {
      setIsStale(false);
    }
  }, [pipelineStatus, currentStage]);

  const handleSaveStage = async () => {
    if (!stageName.trim()) {
      return;
    }
    const stage = stageName.trim();
    const notebookPath = panel.context.path;

    // Environment is required for the stage
    if (!currentEnv) {
      await showErrorMessage(
        "Environment required",
        "Please set an environment for this notebook before setting a stage.",
      );
      return;
    }

    try {
      // Fetch current notebook info to get any existing inputs/outputs
      const notebookInfo = await requestAPI<any>(
        `notebooks?path=${encodeURIComponent(notebookPath)}`,
      );
      const existingInputs = notebookInfo.stage?.inputs || [];
      const existingOutputs = notebookInfo.stage?.outputs || [];

      await setNotebookStageMutation.mutateAsync({
        path: notebookPath,
        stage_name: stage,
        environment: currentEnv,
        inputs: existingInputs,
        outputs: existingOutputs,
      });
      setCurrentStage(stage);
      setIsOpen(false);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to set pipeline stage:", error);
      await showErrorMessage("Failed to set notebook stage", errorMsg);
    }
  };

  const isConfigured = currentStage !== "";
  const label = isConfigured ? `Stage: ${currentStage}` : "Not in pipeline";

  const handlePlayButtonClick = async () => {
    try {
      // Save the notebook before running the stage
      console.log("Saving notebook...");
      const savePromise = panel.context.save();
      if (savePromise) {
        await savePromise;
      }
      console.log("Notebook saved successfully");

      const notebookPath = panel.context.path;

      // Step 1: Create a notebook stage run session
      console.log("Creating run session...");
      const sessionResponse = await requestAPI<any>(
        "notebook/stage/run/session",
        {
          method: "POST",
          body: JSON.stringify({
            notebook_path: notebookPath,
            stage_name: currentStage,
          }),
        },
      );

      console.log("Session created. Restarting kernel and running cells...");

      // Step 2: Restart kernel and wait for it to be ready
      const sessionContext = panel.sessionContext;
      if (sessionContext.session?.kernel) {
        await sessionContext.session.kernel.restart();
        // Wait for kernel to be idle (ready)
        await waitForKernelIdle(sessionContext.session.kernel);
      }

      // Step 3: Run all cells
      await NotebookActions.runAll(panel.content, sessionContext);

      console.log("All cells executed successfully. Finalizing session...");

      // Step 3b: Save notebook after execution to persist outputs
      const postRunSave = panel.context.save();
      if (postRunSave) {
        await postRunSave;
      }
      console.log("Notebook saved after execution");

      // Step 4: Finalize the session with the backend
      await requestAPI<any>("notebook/stage/run/session", {
        method: "PUT",
        body: JSON.stringify({
          notebook_path: notebookPath,
          stage_name: currentStage,
          dvc_stage: sessionResponse.dvc_stage,
          lock_deps: sessionResponse.lock_deps,
          lock_outs: sessionResponse.lock_outs,
        }),
      });

      console.log("Stage run completed and cached successfully!");
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to run stage:", error);
      await showErrorMessage("Failed to run stage", errorMsg);
    }
  };

  return (
    <div className="calkit-badge-with-action">
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
            <h4>Set notebook stage</h4>
            <div className="calkit-form-group">
              <label>Stage name</label>
              <div className="calkit-input-row">
                <input
                  type="text"
                  value={stageName}
                  onChange={(e) => setStageName(e.target.value)}
                  placeholder="e.g., postprocess"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleSaveStage();
                    }
                  }}
                />
                <button
                  onClick={handleSaveStage}
                  disabled={
                    setNotebookStageMutation.isPending || !stageName.trim()
                  }
                >
                  {setNotebookStageMutation.isPending ? "Saving..." : "Save"}
                </button>
              </div>
            </div>
          </div>
        )}
      </BadgeDropdown>
      {isConfigured && (
        <button
          className={`calkit-play-button ${
            isStale ? "calkit-play-button-stale" : ""
          }`}
          onClick={handlePlayButtonClick}
          title={isStale ? "Stage is stale - run to update" : "Run stage"}
        >
          ▶
        </button>
      )}
    </div>
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
  const setNotebookStageMutation = useSetNotebookStage();

  // Load inputs on mount
  useEffect(() => {
    const loadInputs = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebooks?path=${encodeURIComponent(notebookPath)}`,
        );
        setInputs(notebookInfo.stage?.inputs || []);
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
      const notebookInfo = await requestAPI<any>(
        `notebooks?path=${encodeURIComponent(notebookPath)}`,
      );
      const stageName = notebookInfo.stage?.name || "";
      const env = notebookInfo.environment?.name || "";

      // If there's a stage, update it with the new inputs
      if (stageName && env) {
        await setNotebookStageMutation.mutateAsync({
          path: notebookPath,
          stage_name: stageName,
          environment: env,
          inputs: inputs,
          outputs: notebookInfo.stage?.outputs || [],
        });
      }
      setIsOpen(false);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to save inputs:", error);
      await showErrorMessage("Failed to save inputs", errorMsg);
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
  const setNotebookStageMutation = useSetNotebookStage();

  // Load outputs on mount
  useEffect(() => {
    const loadOutputs = async () => {
      try {
        const notebookPath = panel.context.path;
        const notebookInfo = await requestAPI<any>(
          `notebooks?path=${encodeURIComponent(notebookPath)}`,
        );
        setOutputs(notebookInfo.stage?.outputs || []);
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
      const notebookInfo = await requestAPI<any>(
        `notebooks?path=${encodeURIComponent(notebookPath)}`,
      );
      const stageName = notebookInfo.stage?.name || "";
      const env = notebookInfo.environment?.name || "";

      // If there's a stage, update it with the new outputs
      if (stageName && env) {
        await setNotebookStageMutation.mutateAsync({
          path: notebookPath,
          stage_name: stageName,
          environment: env,
          inputs: notebookInfo.stage?.inputs || [],
          outputs: outputs,
        });
      }
      setIsOpen(false);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to save outputs:", error);
      await showErrorMessage("Failed to save outputs", errorMsg);
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
          `notebooks?path=${encodeURIComponent(notebookPath)}`,
        );
        setTitle(notebookInfo.stage?.title || "");
        setDescription(notebookInfo.stage?.description || "");
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
    return (
      <QueryClientProvider client={queryClient}>
        <NotebookToolbar panel={this.panel} translator={this.translator} />
      </QueryClientProvider>
    );
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
