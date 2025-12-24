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
interface EnvironmentEditorProps {
  initialName?: string;
  initialKind?: string;
  initialPackages?: string[];
  mode: "create" | "edit";
}

/**
 * The body component for the environment editor dialog
 */
const EnvironmentEditorBody: React.FC<
  EnvironmentEditorProps & {
    onUpdate: (data: {
      name: string;
      kind: string;
      packages: string[];
    }) => void;
  }
> = ({
  initialName = "",
  initialKind = "uv-venv",
  initialPackages = [],
  mode,
  onUpdate,
}) => {
  const [name, setName] = useState(initialName);
  const [kind, setKind] = useState(initialKind);
  const [packages, setPackages] = useState<string[]>(initialPackages);
  const [newPackage, setNewPackage] = useState("");

  React.useEffect(() => {
    onUpdate({ name, kind, packages });
  }, [name, kind, packages, onUpdate]);

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
          onChange={(e) => setKind(e.target.value)}
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
    </div>
  );
};

/**
 * A widget wrapper for the environment editor body
 */
class EnvironmentEditorWidget extends ReactWidget {
  private _data: { name: string; kind: string; packages: string[] };

  constructor(private options: EnvironmentEditorProps) {
    super();
    this._data = {
      name: options.initialName || "",
      kind: options.initialKind || "uv-venv",
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

  getValue(): { name: string; kind: string; packages: string[] } {
    return this._data;
  }
}

/**
 * Show a dialog to create or edit an environment
 */
export async function showEnvironmentEditor(
  options: EnvironmentEditorProps,
): Promise<{ name: string; kind: string; packages: string[] } | null> {
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
      return data;
    }
  }
  return null;
}
