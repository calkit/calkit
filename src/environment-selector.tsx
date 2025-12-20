import { ReactWidget } from "@jupyterlab/apputils";
import { NotebookPanel } from "@jupyterlab/notebook";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import React, { useEffect, useState } from "react";
import { requestAPI } from "./request";
import { calkitIcon } from "./icons";
import { showEnvironmentEditor } from "./environment-editor";

/**
 * Environment selector component
 */
const EnvironmentSelector: React.FC<{
  panel: NotebookPanel;
  translator?: ITranslator;
}> = ({ panel, translator }) => {
  const trans = (translator || nullTranslator).load("calkit");
  const [environments, setEnvironments] = useState<Record<string, any>>({});
  const [currentEnv, setCurrentEnv] = useState<string>("");
  const [loading, setLoading] = useState(true);

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

  const handleEnvironmentChange = async (envName: string) => {
    setCurrentEnv(envName);
    // TODO: Switch kernel to match environment
    console.log(`Switching to environment: ${envName}`);
  };

  const handleCreateEnvironment = async () => {
    const result = await showEnvironmentEditor({ mode: "create" });
    if (!result) {
      return;
    }
    try {
      await requestAPI("environment/create", {
        method: "POST",
        body: JSON.stringify({
          name: result.name,
          kind: result.kind,
          packages: result.packages,
        }),
      });
      // Refresh environments
      const info = await requestAPI<any>("project");
      setEnvironments(info.environments || {});
      setCurrentEnv(result.name);
    } catch (error) {
      console.error("Failed to create environment:", error);
    }
  };

  const handleEditEnvironment = async () => {
    if (!currentEnv) {
      return;
    }
    const currentEnvData = environments[currentEnv];
    const result = await showEnvironmentEditor({
      mode: "edit",
      initialName: currentEnv,
      initialKind: currentEnvData?.kind || "uv-venv",
      initialPackages: currentEnvData?.packages || [],
    });
    if (!result) {
      return;
    }
    try {
      await requestAPI("environment/update", {
        method: "POST",
        body: JSON.stringify({
          name: currentEnv,
          kind: result.kind,
          packages: result.packages,
        }),
      });
      // Refresh environments
      const info = await requestAPI<any>("project");
      setEnvironments(info.environments || {});
    } catch (error) {
      console.error("Failed to update environment:", error);
    }
  };

  if (loading) {
    return (
      <div className="calkit-env-selector">
        <span className="calkit-env-label">Loading...</span>
      </div>
    );
  }

  const envNames = Object.keys(environments);

  return (
    <div className="calkit-env-selector">
      <span className="calkit-env-icon">
        <calkitIcon.react height={16} />
      </span>
      <select
        className="calkit-env-dropdown"
        value={currentEnv}
        onChange={(e) => handleEnvironmentChange(e.target.value)}
        title={trans.__("Select Calkit Environment")}
      >
        {envNames.length === 0 && (
          <option value="">{trans.__("No environments")}</option>
        )}
        {envNames.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <button
        className="calkit-env-button"
        onClick={handleEditEnvironment}
        title={trans.__("Edit environment packages")}
        disabled={!currentEnv}
      >
        ✏️
      </button>
      <button
        className="calkit-env-button"
        onClick={handleCreateEnvironment}
        title={trans.__("Create new environment")}
      >
        ➕
      </button>
    </div>
  );
};

/**
 * Widget wrapper for the environment selector
 */
export class EnvironmentSelectorWidget extends ReactWidget {
  constructor(
    private panel: NotebookPanel,
    private translator?: ITranslator,
  ) {
    super();
    this.addClass("calkit-env-selector-widget");
  }

  render() {
    return (
      <EnvironmentSelector panel={this.panel} translator={this.translator} />
    );
  }
}

/**
 * Create environment selector for notebook toolbar
 */
export function createEnvironmentSelector(
  panel: NotebookPanel,
  translator?: ITranslator,
): EnvironmentSelectorWidget {
  return new EnvironmentSelectorWidget(panel, translator);
}
