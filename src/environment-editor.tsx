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
      packages: string[];
    }) => void;
    onSubmit: (data: {
      name: string;
      kind: string;
      path: string;
      packages: string[];
    }) => Promise<void>;
    onClose: () => void;
  }
> = ({
  initialName = "",
  initialKind = "uv-venv",
  initialPath = "",
  initialPackages = [],
  mode,
  onUpdate,
  onSubmit,
  onClose,
}) => {
  // Default paths based on environment kind
  const getDefaultPath = (kind: string) => {
    switch (kind) {
      case "uv-venv":
      case "venv":
        return "requirements.txt";
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

  const [name, setName] = useState(initialName);
  const [kind, setKind] = useState(initialKind);
  const [path, setPath] = useState(initialPath || getDefaultPath(initialKind));
  const [packages, setPackages] = useState<string[]>(initialPackages);
  const [newPackage, setNewPackage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  React.useEffect(() => {
    onUpdate({ name, kind, path, packages });
  }, [name, kind, path, packages, onUpdate]);

  // Update path when kind changes (in create mode)
  const handleKindChange = (newKind: string) => {
    setKind(newKind);
    if (mode === "create") {
      setPath(getDefaultPath(newKind));
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
        <label htmlFor="env-name">Environment name:</label>
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
        <label htmlFor="env-kind">Environment kind:</label>
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
      <div className="calkit-env-editor-field">
        <label htmlFor="env-path">Path:</label>
        <input
          id="env-path"
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder={getDefaultPath(kind)}
          title="Path to requirements/environment file"
        />
      </div>
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
      <div className="calkit-env-editor-actions">
        {submitError && (
          <div className="calkit-env-error" title={submitError}>
            {submitError}
          </div>
        )}
        <button
          type="button"
          className="jp-Dialog-button jp-mod-accept"
          disabled={isSubmitting || !name.trim()}
          onClick={async () => {
            setSubmitError(null);
            setIsSubmitting(true);
            try {
              await onSubmit({ name, kind, path, packages });
              onClose();
            } catch (err: any) {
              const msg =
                typeof err?.message === "string"
                  ? err.message
                  : err?.message?.error || JSON.stringify(err?.message || err);
              setSubmitError(msg);
            } finally {
              setIsSubmitting(false);
            }
          }}
        >
          {isSubmitting
            ? mode === "create"
              ? "Creating…"
              : "Saving…"
            : mode === "create"
            ? "Create"
            : "Save"}
        </button>
      </div>
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
    packages: string[];
  };

  constructor(
    private options: IEnvironmentEditorProps & {
      onSubmit: (data: {
        name: string;
        kind: string;
        path: string;
        packages: string[];
      }) => Promise<void>;
      onClose: () => void;
    },
  ) {
    super();
    const getDefaultPath = (kind: string) => {
      switch (kind) {
        case "uv-venv":
        case "venv":
          return "requirements.txt";
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
    const defaultPath = getDefaultPath(options.initialKind || "uv-venv");
    const initPath = options.initialPath || defaultPath;
    this._data = {
      name: options.initialName || "",
      kind: options.initialKind || "uv-venv",
      path: initPath,
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
        onSubmit={this.options.onSubmit}
        onClose={this.options.onClose}
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
  let disposeRef: () => void = () => {};
  const widget = new EnvironmentEditorWidget({
    ...options,
    onClose: () => disposeRef(),
  });
  const dialog = new Dialog({
    title:
      options.mode === "create" ? "Create environment" : "Edit environment",
    body: widget,
    buttons: [Dialog.cancelButton()],
  });
  disposeRef = () => dialog.dispose();
  await dialog.launch();
}
