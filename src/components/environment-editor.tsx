import React, { useState } from "react";
import { Dialog } from "@jupyterlab/apputils";
import { ReactWidget } from "@jupyterlab/apputils";

/**
 * Predefined package groups
 */
const PACKAGE_GROUPS: Record<string, string[]> = {
  PyData: [
    "numpy",
    "scipy",
    "pandas",
    "polars",
    "matplotlib",
    "statsmodels",
    "scikit-learn",
    "seaborn",
    "duckdb",
    "plotly",
    "altair",
    "bokeh",
  ],
};

/**
 * Props for the environment editor dialog body
 */
interface IEnvironmentEditorProps {
  initialName?: string;
  initialKind?: string;
  initialPath?: string;
  initialPrefix?: string;
  initialPackages?: string[];
  mode: "create" | "edit";
}

/**
 * The body component for the environment editor dialog
 */
const EnvironmentEditorBody: React.FC<
  IEnvironmentEditorProps & {
    onUpdate: (data: {
      name: string;
      kind: string;
      path: string;
      prefix?: string;
      packages: string[];
    }) => void;
  }
> = ({
  initialName = "",
  initialKind = "uv-venv",
  initialPath = "",
  initialPrefix = "",
  initialPackages = [],
  mode,
  onUpdate,
}) => {
  // Default paths based on environment kind
  const getDefaultPath = (kind: string, envName: string = "") => {
    switch (kind) {
      case "uv-venv":
      case "venv":
        return `.calkit/envs/${envName || "{name}"}.txt`;
      case "conda":
        return "environment.yml";
      case "pixi":
        return "pixi.toml";
      case "julia":
        return "project/Project.toml";
      default:
        return "";
    }
  };

  // Default prefix for venv-based environments
  const getDefaultPrefix = (kind: string, envName: string = "") => {
    switch (kind) {
      case "uv-venv":
      case "venv":
        return `.calkit/venvs/${envName || "{name}"}/.venv`;
      default:
        return "";
    }
  };

  const [name, setName] = useState(initialName);
  const [kind, setKind] = useState(initialKind);
  const [path, setPath] = useState(
    initialPath || getDefaultPath(initialKind, initialName),
  );
  const [prefix, setPrefix] = useState(
    initialPrefix || getDefaultPrefix(initialKind, initialName),
  );
  const [packages, setPackages] = useState<string[]>(initialPackages);
  const [newPackage, setNewPackage] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [userEditedPath, setUserEditedPath] = useState(!!initialPath);
  const [userEditedPrefix, setUserEditedPrefix] = useState(!!initialPrefix);

  React.useEffect(() => {
    const data: any = { name, kind, path, packages };
    if (kind === "uv-venv" || kind === "venv") {
      data.prefix = prefix;
    }
    onUpdate(data);
  }, [name, kind, path, prefix, packages, onUpdate]);

  // Update path and prefix when name changes (in create mode)
  React.useEffect(() => {
    if (mode === "create") {
      if (!userEditedPath) {
        setPath(getDefaultPath(kind, name));
      }
      if (!userEditedPrefix) {
        setPrefix(getDefaultPrefix(kind, name));
      }
    }
  }, [name, kind, mode, userEditedPath, userEditedPrefix]);

  // Update path when kind changes (in create mode)
  const handleKindChange = (newKind: string) => {
    setKind(newKind);
    if (mode === "create") {
      if (!userEditedPath) {
        setPath(getDefaultPath(newKind, name));
      }
      if (!userEditedPrefix) {
        setPrefix(getDefaultPrefix(newKind, name));
      }
    }
  };

  const handleAddPackage = () => {
    if (newPackage.trim() && !packages.includes(newPackage.trim())) {
      setPackages([...packages, newPackage.trim()]);
      setNewPackage("");
    }
  };

  const handleRemovePackage = (pkg: string) => {
    setPackages(packages.filter((p) => p !== pkg));
  };

  const handleSelectPackageGroup = (groupName: string) => {
    const groupPackages = PACKAGE_GROUPS[groupName] || [];
    // Merge with existing packages, ensuring no duplicates and ipykernel is included
    const merged = new Set([
      ...packages,
      ...groupPackages,
      ...(kind === "uv-venv" ||
      kind === "venv" ||
      kind === "conda" ||
      kind === "julia"
        ? ["ipykernel"]
        : []),
    ]);
    setPackages(Array.from(merged).sort());
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      handleAddPackage();
    }
  };

  const showPackages =
    kind === "uv-venv" ||
    kind === "venv" ||
    kind === "julia" ||
    kind === "conda";

  return (
    <div className="calkit-env-editor">
      <div className="calkit-env-editor-field">
        <label htmlFor="env-name">Name:</label>
        <input
          id="env-name"
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={mode === "edit"}
          placeholder="my-environment"
          autoFocus={mode === "create"}
        />
      </div>
      <div className="calkit-env-editor-field">
        <label htmlFor="env-kind">Kind:</label>
        <select
          id="env-kind"
          value={kind}
          onChange={(e) => handleKindChange(e.target.value)}
        >
          <option value="uv-venv">uv-venv (Python)</option>
          <option value="venv">venv (Python)</option>
          <option value="julia">Julia</option>
          <option value="conda">Conda</option>
          <option value="docker">Docker</option>
        </select>
      </div>
      {showPackages && (
        <div className="calkit-env-editor-field">
          <label>Packages:</label>
          <div className="calkit-env-packages-list">
            {packages.map((pkg) => (
              <div key={pkg} className="calkit-env-package-item">
                <span className="calkit-env-package-name">{pkg}</span>
                <button
                  type="button"
                  className="calkit-env-package-remove"
                  onClick={() => handleRemovePackage(pkg)}
                  title="Remove package"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <div className="calkit-env-package-input-container">
            <input
              type="text"
              value={newPackage}
              onChange={(e) => setNewPackage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Add package..."
              className="calkit-env-package-add-input"
            />
            <button
              type="button"
              onClick={handleAddPackage}
              className="calkit-env-package-add-button"
              disabled={!newPackage.trim()}
            >
              +
            </button>
          </div>
        </div>
      )}
      {/* Package groups */}
      {showPackages && (
        <div className="calkit-env-editor-field">
          <label>Package groups:</label>
          <div className="calkit-env-package-groups">
            {Object.keys(PACKAGE_GROUPS).map((groupName) => (
              <button
                key={groupName}
                type="button"
                className="calkit-env-package-group-btn"
                onClick={() => handleSelectPackageGroup(groupName)}
                title={`Add packages from ${groupName}: ${PACKAGE_GROUPS[
                  groupName
                ].join(", ")}`}
              >
                + {groupName}
              </button>
            ))}
          </div>
        </div>
      )}
      {/* Advanced section for venv-based environments */}
      {(kind === "uv-venv" || kind === "venv") && (
        <div className="calkit-env-editor-advanced">
          <div
            className="calkit-env-editor-advanced-toggle"
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            <span className="calkit-env-editor-chevron">
              {showAdvanced ? "▼" : "▶"}
            </span>
            <span>Advanced</span>
          </div>
          {showAdvanced && (
            <div className="calkit-env-editor-advanced-fields">
              <div className="calkit-env-editor-field">
                <label htmlFor="env-path">Path:</label>
                <input
                  id="env-path"
                  type="text"
                  value={path}
                  onChange={(e) => {
                    setPath(e.target.value);
                    setUserEditedPath(true);
                  }}
                  placeholder={getDefaultPath(kind, name)}
                  title="Path to requirements/environment file"
                />
              </div>
              <div className="calkit-env-editor-field">
                <label htmlFor="env-prefix">Virtual environment prefix:</label>
                <input
                  id="env-prefix"
                  type="text"
                  value={prefix}
                  onChange={(e) => {
                    setPrefix(e.target.value);
                    setUserEditedPrefix(true);
                  }}
                  placeholder={getDefaultPrefix(kind, name)}
                  title="Path to virtual environment directory"
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/**
 * A widget wrapper for the environment editor body
 */
class EnvironmentEditorWidget extends ReactWidget {
  private _data: {
    name: string;
    kind: string;
    path: string;
    prefix?: string;
    packages: string[];
  };

  constructor(
    private options: IEnvironmentEditorProps & {
      onUpdate?: (data: {
        name: string;
        kind: string;
        path: string;
        prefix?: string;
        packages: string[];
      }) => void;
    },
  ) {
    super();
    const getDefaultPath = (kind: string, envName: string = "") => {
      switch (kind) {
        case "uv-venv":
        case "venv":
          return `.calkit/envs/${envName || "{name}"}.txt`;
        case "conda":
          return "environment.yml";
        case "pixi":
          return "pixi.toml";
        case "julia":
          return "project/Project.toml";
        default:
          return "";
      }
    };
    const getDefaultPrefix = (kind: string, envName: string = "") => {
      switch (kind) {
        case "uv-venv":
        case "venv":
          return `.calkit/venvs/${envName || "{name}"}/.venv`;
        default:
          return "";
      }
    };
    const envName = options.initialName || "";
    const kind = options.initialKind || "uv-venv";
    const defaultPath = getDefaultPath(kind, envName);
    const defaultPrefix = getDefaultPrefix(kind, envName);
    const initPath = options.initialPath || defaultPath;
    const initPrefix =
      options.initialPrefix ||
      (kind === "uv-venv" || kind === "venv" ? defaultPrefix : "");
    this._data = {
      name: envName,
      kind,
      path: initPath,
      prefix: initPrefix,
      packages: options.initialPackages || [],
    };
  }

  render(): JSX.Element {
    return (
      <EnvironmentEditorBody
        {...this.options}
        onUpdate={(data) => {
          this._data = data;
        }}
      />
    );
  }

  getValue(): {
    name: string;
    kind: string;
    path: string;
    packages: string[];
  } {
    return this._data;
  }
}

/**
 * Show a dialog to create or edit an environment
 */
export async function showEnvironmentEditor(
  options: IEnvironmentEditorProps & {
    onSubmit: (data: {
      name: string;
      kind: string;
      path: string;
      packages: string[];
    }) => Promise<void>;
  },
): Promise<void> {
  const widget = new EnvironmentEditorWidget(options);
  const dialog = new Dialog({
    title:
      options.mode === "create" ? "Create environment" : "Edit environment",
    body: widget,
    buttons: [
      Dialog.cancelButton(),
      Dialog.okButton({ label: options.mode === "create" ? "Create" : "Save" }),
    ],
  });
  const result = await dialog.launch();
  if (result.button.accept) {
    const data = widget.getValue();
    if (data.name.trim()) {
      await options.onSubmit(data);
    }
  }
}
