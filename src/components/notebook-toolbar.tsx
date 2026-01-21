import { ReactWidget, showErrorMessage } from "@jupyterlab/apputils";
import { NotebookPanel, NotebookActions } from "@jupyterlab/notebook";
import { ITranslator } from "@jupyterlab/translation";
import React, { useEffect, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { requestAPI } from "../request";
import { queryClient } from "../queryClient";
import { infoLetterIcon } from "../icons";
import { showEnvironmentEditor } from "./environment-editor";
import {
  usePipelineStatus,
  useSetNotebookStage,
  useCreateEnvironment,
  useUpdateEnvironment,
  useSetNotebookEnvironment,
  useEnvironments,
} from "../hooks/useQueries";
import { isFeatureEnabled } from "../feature-flags";

/**
 * Extract a readable error message from various error types
 */
function getErrorMessage(error: unknown): string {
  if (!error) {
    return "Unknown error";
  }
  // If it's a string, return it directly
  if (typeof error === "string") {
    return error;
  }

  // If it's an Error object, get the message
  if (error instanceof Error) {
    // Check if message is "[object Object]" - this happens when an object was passed as the message
    if (error.message !== "[object Object]") {
      return error.message;
    }
  }

  // Handle object-like errors (including ServerConnection.ResponseError)
  if (typeof error === "object") {
    const err = error as any;

    // For ServerConnection.ResponseError, the message property contains the parsed response data
    // If message is an object with error or message fields, extract those
    if (err.message && typeof err.message === "object") {
      if (err.message.error && typeof err.message.error === "string") {
        return err.message.error;
      }
      if (err.message.message && typeof err.message.message === "string") {
        return err.message.message;
      }
      // Try to stringify the message object
      try {
        const stringified = JSON.stringify(err.message, null, 2);
        if (stringified && stringified !== "{}" && stringified !== "{}") {
          return stringified;
        }
      } catch {
        // JSON.stringify can fail
      }
    }

    // Check for traceback (often contains the response data)
    if (err.traceback) {
      // If traceback is a string, return it (but not if empty)
      if (typeof err.traceback === "string" && err.traceback.trim()) {
        return err.traceback;
      }
      // If traceback is an object with error property
      if (typeof err.traceback === "object") {
        if (err.traceback.error && typeof err.traceback.error === "string") {
          return err.traceback.error;
        }
        if (
          err.traceback.message &&
          typeof err.traceback.message === "string"
        ) {
          return err.traceback.message;
        }
        // Try to stringify the traceback object
        try {
          const stringified = JSON.stringify(err.traceback, null, 2);
          if (stringified && stringified !== "{}" && stringified !== "{}") {
            return stringified;
          }
        } catch {
          // JSON.stringify can fail
        }
      }
    }

    // Check for response object (from ServerConnection.ResponseError)
    if (err.response && typeof err.response === "object") {
      const response = err.response;

      // Try to extract message from response
      if (response.message && typeof response.message === "string") {
        return response.message;
      }
      if (response.error && typeof response.error === "string") {
        return response.error;
      }
    }

    // Try to extract message from various possible locations
    const possibleMessages = [err.error, err.reason];

    for (const msg of possibleMessages) {
      if (msg && typeof msg === "string" && msg !== "[object Object]") {
        return msg;
      }
      // If message itself is an object with error property
      if (msg && typeof msg === "object") {
        if (msg.message && typeof msg.message === "string") {
          return msg.message;
        }
        if (msg.error && typeof msg.error === "string") {
          return msg.error;
        }
      }
    }

    // Try to stringify the object in a readable way
    try {
      const stringified = JSON.stringify(error, null, 2);
      if (stringified && stringified !== "{}" && stringified !== "{}") {
        return stringified;
      }
    } catch {
      // JSON.stringify can fail for circular references
    }
  }

  // Last resort
  return String(error);
}

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
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [dropdownPosition, setDropdownPosition] = useState<{
    top: number;
    left: number;
  } | null>(null);

  useEffect(() => {
    if (!isOpen || !buttonRef.current) {
      return;
    }

    // Calculate dropdown position based on button position
    const updatePosition = () => {
      if (!buttonRef.current) {
        return;
      }
      const rect = buttonRef.current.getBoundingClientRect();
      setDropdownPosition({
        top: rect.bottom + 4,
        left: rect.right,
      });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);

    return () => {
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [isOpen]);

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
        ref={buttonRef}
        className={buttonClasses}
        onClick={onToggle}
        title={isConfigured ? label : `${label} (not configured)`}
      >
        {labelNode || label}
      </button>
      {isOpen &&
        dropdownPosition &&
        ReactDOM.createPortal(
          <div
            className="calkit-badge-dropdown"
            style={{
              position: "fixed",
              top: `${dropdownPosition.top}px`,
              left: `${dropdownPosition.left}px`,
              transform: "translateX(-100%)",
            }}
          >
            {children}
          </div>,
          document.body,
        )}
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
  const [currentEnv, setCurrentEnv] = useState<string>("");
  const { data: allEnvironments = {}, isLoading: isLoadingEnvs } =
    useEnvironments();

  const createEnvironmentMutation = useCreateEnvironment();
  const updateEnvironmentMutation = useUpdateEnvironment();
  const setNotebookEnvMutation = useSetNotebookEnvironment();
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

  // Fetch notebook's specific environment on mount or when panel changes
  useEffect(() => {
    const fetchNotebookEnvironment = async () => {
      const notebookPath = panel.context.path;
      try {
        const nbEnvData = await requestAPI<any>(
          `notebooks?path=${encodeURIComponent(notebookPath)}`,
        );
        if (nbEnvData.environment?.name) {
          setCurrentEnv(nbEnvData.environment.name);
          // Ensure kernel matches environment when opening notebook
          await switchKernelForEnvironment(nbEnvData.environment.name);
        } else {
          setCurrentEnv("");
        }
      } catch (error) {
        console.warn("Failed to fetch notebook environment:", error);
        setCurrentEnv("");
      }
    };

    fetchNotebookEnvironment();
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
      // Keep the selector open after change to show details
    }
  };

  const handleCreateEnvironment = async () => {
    // Project detection and naming now happens naturally in the backend
    await showEnvironmentEditor({
      mode: "create",
      onSubmit: async ({ name, kind, path, packages, prefix, python }) => {
        await createEnvironmentMutation.mutateAsync({
          name,
          kind,
          path,
          packages,
          prefix,
          python,
        });
        // Associate environment to this notebook on the backend
        await setNotebookEnvMutation.mutateAsync({
          path: panel.context.path,
          environment: name,
        });
        // Switch kernel to match environment
        await switchKernelForEnvironment(name);
        // Set current env - React Query will auto-update from the invalidation
        setCurrentEnv(name);
      },
    });
  };

  const handleEditEnvironment = async () => {
    if (!currentEnv) {
      return;
    }

    const envData = allEnvironments[currentEnv] || {};
    await showEnvironmentEditor({
      mode: "edit",
      initialName: currentEnv,
      initialKind: envData.kind || "uv-venv",
      initialPath: envData.path,
      initialPrefix: envData.prefix,
      initialPython: envData.python || "3.14",
      initialPackages: envData.packages || [],
      existingEnvironment: {
        name: currentEnv,
        kind: envData.kind || "uv-venv",
        path: envData.path,
        prefix: envData.prefix,
        python: envData.python || "3.14",
        packages: envData.packages || [],
      },
      onSubmit: async (
        { name, kind, path, prefix, packages, python },
        initialData,
      ) => {
        await updateEnvironmentMutation.mutateAsync({
          existing: initialData || {
            name: currentEnv,
            kind: envData.kind || "uv-venv",
            path: envData.path,
            prefix: envData.prefix,
            python: envData.python || "3.14",
            packages: envData.packages || [],
          },
          updated: { name, kind, path, prefix, packages, python },
        });
        // React Query will auto-update from the invalidation
        setCurrentEnv(name);
        setIsOpen(false);
      },
    });
  };

  const envNames = Object.keys(allEnvironments);
  const selectedEnv = currentEnv ? allEnvironments[currentEnv] : null;
  const pythonVersion =
    selectedEnv?.python || selectedEnv?.python_version || "Unknown";
  const packagesList = Array.isArray(selectedEnv?.packages)
    ? selectedEnv.packages
    : [];
  const envSelectId = `calkit-env-select-${panel.id || "default"}`;
  const hasCurrentEnvOption = currentEnv && envNames.includes(currentEnv);
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
      {isLoadingEnvs ? (
        <div className="calkit-dropdown-content">Loading...</div>
      ) : (
        <div className="calkit-dropdown-content">
          <div className="calkit-dropdown-section">
            <h4>Select environment</h4>
            {envNames.length === 0 ? (
              <div>
                <p>No environments available</p>
                <button
                  className="calkit-dropdown-button"
                  onClick={handleCreateEnvironment}
                  disabled={switchingKernel}
                >
                  Create new environment
                </button>
              </div>
            ) : (
              <div className="calkit-form-group">
                <select
                  id={envSelectId}
                  value={currentEnv}
                  onChange={(e) => {
                    const value = e.target.value;
                    if (!value || switchingKernel) {
                      return;
                    }
                    if (value === "__create__") {
                      void handleCreateEnvironment();
                      return;
                    }
                    void handleEnvironmentSelect(value);
                  }}
                  disabled={switchingKernel || envNames.length === 0}
                >
                  <option value="">Select an environment</option>
                  <option value="__create__">Create new environment...</option>
                  {currentEnv && !hasCurrentEnvOption && (
                    <option value={currentEnv}>
                      {currentEnv} (not listed)
                    </option>
                  )}
                  {envNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {selectedEnv ? (
              <div className="calkit-env-details">
                <p>
                  <strong>Python:</strong> {pythonVersion}
                </p>
                <div className="calkit-env-packages">
                  <div className="calkit-env-packages-header">
                    <strong>Packages:</strong>
                  </div>
                  {packagesList.length === 0 ? (
                    <p className="calkit-env-packages-empty">No packages</p>
                  ) : (
                    <ul className="calkit-env-packages-list">
                      {packagesList.map((pkg: string, idx: number) => (
                        <li key={idx} className="calkit-env-package-item">
                          {pkg}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            ) : (
              envNames.length > 0 && (
                <p className="calkit-note">
                  {currentEnv && !hasCurrentEnvOption
                    ? "Current notebook environment is not listed."
                    : "Select an environment to view details."}
                </p>
              )
            )}
          </div>
          <div className="calkit-dropdown-divider" />
          <div className="calkit-dropdown-actions">
            <button
              className="calkit-dropdown-button"
              onClick={handleEditEnvironment}
              disabled={!currentEnv || !hasCurrentEnvOption}
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
  const [isExecuting, setIsExecuting] = useState(false);
  const [executedIpynbStorage, setExecutedIpynbStorage] =
    useState<string>("git");
  const [htmlStorage, setHtmlStorage] = useState<string>("git");
  const { data: pipelineStatus } = usePipelineStatus();
  const setNotebookStageMutation = useSetNotebookStage();

  const waitForKernelIdle = async (kernel: any) => {
    if (!kernel) {
      return;
    }
    if (kernel.status === "idle") {
      return;
    }
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

  const hasCellErrors = (): boolean => {
    const cells = panel.content.model?.cells;
    if (!cells) {
      return false;
    }
    for (let i = 0; i < cells.length; i++) {
      const cell = cells.get(i);
      const outputs = (cell as any).outputs?.toJSON?.() || [];
      const cellOutputArray = Array.isArray(outputs) ? outputs : [];
      for (const output of cellOutputArray) {
        if (output?.output_type === "error") {
          return true;
        }
      }
    }
    return false;
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
        setExecutedIpynbStorage(
          notebookInfo.stage?.executed_ipynb_storage || "git",
        );
        setHtmlStorage(notebookInfo.stage?.html_storage || "git");

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

    try {
      // Fetch current notebook info to get any existing inputs/outputs
      const notebookInfo = await requestAPI<any>(
        `notebooks?path=${encodeURIComponent(notebookPath)}`,
      );
      const envName = notebookInfo.environment?.name || currentEnv || "";

      // Environment is required for the stage
      if (!envName) {
        await showErrorMessage(
          "Environment required",
          "Please set an environment for this notebook before setting a stage.",
        );
        return;
      }
      const existingInputs = notebookInfo.stage?.inputs || [];
      const existingOutputs = notebookInfo.stage?.outputs || [];

      await setNotebookStageMutation.mutateAsync({
        path: notebookPath,
        stage_name: stage,
        environment: envName,
        inputs: existingInputs,
        outputs: existingOutputs,
        executed_ipynb_storage:
          executedIpynbStorage === "none" ? null : executedIpynbStorage,
        html_storage: htmlStorage === "none" ? null : htmlStorage,
      });
      setCurrentStage(stage);
      setIsOpen(false);
      // Invalidate pipeline status since adding/updating a stage affects it
      void queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.error("Failed to set pipeline stage:", error);
      await showErrorMessage("Failed to set notebook stage", errorMsg);
    }
  };

  const isConfigured = currentStage !== "";
  const label = isConfigured ? `Stage: ${currentStage}` : "Not in pipeline";

  const handlePlayButtonClick = async () => {
    setIsExecuting(true);
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

      console.log("All cells executed. Checking for errors...");

      // Step 3b: Save notebook after execution to persist outputs
      const postRunSave = panel.context.save();
      if (postRunSave) {
        await postRunSave;
      }
      console.log("Notebook saved after execution");

      // Check if any cells raised an exception
      if (hasCellErrors()) {
        console.log("Cells have errors. Skipping session finalization.");
        return;
      }

      console.log("No errors detected. Finalizing session...");

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
      // Invalidate queries to immediately refresh UI state
      void queryClient.invalidateQueries({ queryKey: ["pipeline", "status"] });
      void queryClient.invalidateQueries({ queryKey: ["notebooks"] });
    } catch (error) {
      const errorMsg = getErrorMessage(error);
      await showErrorMessage("Failed to run stage", errorMsg);
    } finally {
      setIsExecuting(false);
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
              <input
                type="text"
                value={stageName}
                onChange={(e) => setStageName(e.target.value)}
                placeholder="ex: postprocess"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleSaveStage();
                  }
                }}
                autoComplete="off"
              />
            </div>
            <div className="calkit-form-group">
              <label htmlFor="executed-ipynb-storage">
                Executed ipynb storage
              </label>
              <select
                id="executed-ipynb-storage"
                value={executedIpynbStorage}
                onChange={(e) => setExecutedIpynbStorage(e.target.value)}
              >
                <option value="git">Git</option>
                <option value="dvc">DVC</option>
                <option value="none">None</option>
              </select>
            </div>
            <div className="calkit-form-group">
              <label htmlFor="html-storage">HTML storage</label>
              <select
                id="html-storage"
                value={htmlStorage}
                onChange={(e) => setHtmlStorage(e.target.value)}
              >
                <option value="git">Git</option>
                <option value="dvc">DVC</option>
                <option value="none">None</option>
              </select>
            </div>
            <div className="calkit-form-actions">
              <button
                className="calkit-primary-button"
                onClick={handleSaveStage}
                disabled={
                  setNotebookStageMutation.isPending || !stageName.trim()
                }
              >
                {setNotebookStageMutation.isPending ? "Saving..." : "Save"}
              </button>
            </div>
          </div>
        )}
      </BadgeDropdown>
      {isConfigured && (
        <button
          className={`calkit-play-button ${
            isStale ? "calkit-play-button-stale" : ""
          } ${isExecuting ? "calkit-play-button-executing" : ""}`}
          onClick={handlePlayButtonClick}
          disabled={isExecuting}
          title={
            isExecuting
              ? "Executing notebook..."
              : isStale
              ? "Stage is stale - run to update"
              : "Run stage"
          }
        >
          {isExecuting ? <span className="calkit-spinner" /> : "▶"}
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
        {isFeatureEnabled("autoDetectInputsOutputs") && (
          <button className="calkit-dropdown-button" onClick={handleAutoDetect}>
            🔍 Auto-Detect Inputs
          </button>
        )}
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
          <label>Add new input:</label>
          <div className="calkit-input-row">
            <input
              type="text"
              value={manualInput}
              onChange={(e) => setManualInput(e.target.value)}
              placeholder="ex: data/raw.csv"
              onKeyPress={(e) => {
                if (e.key === "Enter") {
                  handleAddManual();
                }
              }}
              autoComplete="off"
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
  const [outputs, setOutputs] = useState<
    Array<{ path: string; storage: string }>
  >([]);
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
        const rawOutputs = notebookInfo.stage?.outputs || [];
        // Normalize outputs to objects with path and storage
        const normalizedOutputs = rawOutputs.map((output: any) => {
          if (typeof output === "string") {
            return { path: output, storage: "dvc" };
          }
          return output;
        });
        setOutputs(normalizedOutputs);
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
      const detectedOutputs = result.outputs || [];
      // Convert detected outputs to objects with default DVC storage
      const normalizedOutputs = detectedOutputs.map((output: any) => {
        if (typeof output === "string") {
          return { path: output, storage: "dvc" };
        }
        return output;
      });
      setOutputs(normalizedOutputs);
    } catch (error) {
      console.error("Failed to auto-detect outputs:", error);
      alert("Failed to auto-detect outputs");
    }
  };

  const handleAddManual = () => {
    if (manualOutput.trim()) {
      setOutputs([...outputs, { path: manualOutput.trim(), storage: "dvc" }]);
      setManualOutput("");
    }
  };

  const handleRemoveOutput = (index: number) => {
    setOutputs(outputs.filter((_, i) => i !== index));
  };

  const handleStorageChange = (index: number, storage: string) => {
    const newOutputs = [...outputs];
    newOutputs[index].storage = storage;
    setOutputs(newOutputs);
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
        // Normalize outputs: convert "none" storage to null
        const normalizedOutputs = outputs.map((output) => ({
          ...output,
          storage: output.storage === "none" ? null : output.storage,
        }));
        await setNotebookStageMutation.mutateAsync({
          path: notebookPath,
          stage_name: stageName,
          environment: env,
          inputs: notebookInfo.stage?.inputs || [],
          outputs: normalizedOutputs,
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
        {isFeatureEnabled("autoDetectInputsOutputs") && (
          <button className="calkit-dropdown-button" onClick={handleAutoDetect}>
            🔍 Auto-Detect Outputs
          </button>
        )}
        <div className="calkit-io-list">
          {outputs.map((output, index) => (
            <div key={index} className="calkit-io-item">
              <div className="calkit-io-item-content">
                <div className="calkit-io-field">
                  <span className="calkit-io-label">Path:</span>
                  <span className="calkit-io-value">{output.path}</span>
                </div>
                <div className="calkit-io-field">
                  <label className="calkit-io-label">Storage:</label>
                  <select
                    value={output.storage || ""}
                    onChange={(e) => handleStorageChange(index, e.target.value)}
                    className="calkit-io-storage-select"
                  >
                    <option value="dvc">DVC</option>
                    <option value="git">Git</option>
                    <option value="none">None</option>
                  </select>
                </div>
              </div>
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
          <label>Add new output:</label>
          <div className="calkit-input-row">
            <input
              type="text"
              value={manualOutput}
              onChange={(e) => setManualOutput(e.target.value)}
              placeholder="ex: figures/plot.png"
              onKeyPress={(e) => {
                if (e.key === "Enter") {
                  handleAddManual();
                }
              }}
              autoComplete="off"
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

  if (!isFeatureEnabled("notebookInfoButton")) {
    return null;
  }

  return (
    <BadgeDropdown
      label="Info"
      labelNode={<infoLetterIcon.react height={14} />}
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
            autoComplete="off"
          />
        </div>
        <div className="calkit-form-group">
          <label>Description:</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Describe what this notebook does..."
            rows={5}
            autoComplete="off"
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
