import React, { useCallback, useState } from "react";
import ReactDOM from "react-dom";
import { ReactWidget, Dialog } from "@jupyterlab/apputils";
import { requestAPI } from "./request";
import { showEnvironmentEditor } from "./environment-editor";

interface SectionItem {
  id: string;
  label: string;
  [key: string]: any;
}

/**
 * A sidebar component for Calkit JupyterLab extension.
 * Displays sections for environments, pipeline stages, notebooks, figures,
 * datasets, questions, history, publications, notes, and models.
 */
export const CalkitSidebar: React.FC = () => {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    () => new Set(["environments", "notebooks"]),
  );
  const [expandedEnvironments, setExpandedEnvironments] = useState<Set<string>>(
    new Set(),
  );
  const [sectionData, setSectionData] = useState<Record<string, SectionItem[]>>(
    {},
  );
  const [loading, setLoading] = useState(true);
  const [newPackage, setNewPackage] = useState<Record<string, string>>({});
  const [envContextMenu, setEnvContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
    env?: SectionItem;
  } | null>(null);

  // Close context menu on outside click
  React.useEffect(() => {
    const handleClickOutside = () => {
      setEnvContextMenu(null);
    };
    if (envContextMenu?.visible) {
      document.addEventListener("click", handleClickOutside);
      return () => {
        document.removeEventListener("click", handleClickOutside);
      };
    }
  }, [envContextMenu?.visible]);

  // Fetch sidebar data on mount
  React.useEffect(() => {
    const fetchSectionData = async () => {
      try {
        const info = await requestAPI<any>("project");
        const transformed: Record<string, SectionItem[]> = {
          environments: Object.entries(info.environments || {}).map(
            ([name, obj]) => ({
              id: name,
              label: name,
              ...(typeof obj === "object" ? obj : {}),
            }),
          ),
          pipelineStages: Object.entries(info.pipeline?.stages || {}).map(
            ([name, obj]) => ({
              id: name,
              label: name,
              ...(typeof obj === "object" ? obj : {}),
            }),
          ),
          notebooks: Object.entries(info.notebooks || {}).map(
            ([name, obj]) => ({
              id: name,
              label: name,
              ...(typeof obj === "object" ? obj : {}),
            }),
          ),
          datasets: (info.datasets || []).map((item: any, index: number) => ({
            id: `dataset-${index}`,
            label: item.title || item.path || `Dataset ${index}`,
            ...(typeof item === "object" ? item : {}),
          })),
          questions: (info.questions || []).map((item: any, index: number) => ({
            id: `question-${index}`,
            label:
              typeof item === "string"
                ? item
                : item.question || `Question ${index}`,
            ...(typeof item === "object" ? item : {}),
          })),
          models: Object.entries(info.models || {}).map(([name, obj]) => ({
            id: name,
            label: name,
            ...(typeof obj === "object" ? obj : {}),
          })),
          figures: [],
          history: [],
          publications: [],
          notes: [],
        };
        setSectionData(transformed);
        setLoading(false);
      } catch (error) {
        console.error("Failed to fetch project data:", error);
        setLoading(false);
      }
    };

    fetchSectionData();
  }, []);

  const toggleSection = useCallback((sectionId: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  const toggleEnvironment = useCallback((envId: string) => {
    setExpandedEnvironments((prev) => {
      const next = new Set(prev);
      if (next.has(envId)) {
        next.delete(envId);
      } else {
        next.add(envId);
      }
      return next;
    });
  }, []);

  const handleAddPackage = useCallback(
    async (envName: string) => {
      const packageName = newPackage[envName];
      if (!packageName?.trim()) {
        return;
      }
      try {
        await requestAPI("environment/add-package", {
          method: "POST",
          body: JSON.stringify({
            environment: envName,
            package: packageName.trim(),
          }),
        });
        // Clear input
        setNewPackage((prev) => ({ ...prev, [envName]: "" }));
        // Refresh data
        const info = await requestAPI<any>("project");
        const transformed = {
          ...sectionData,
          environments: Object.entries(info.environments || {}).map(
            ([name, obj]) => ({
              id: name,
              label: name,
              ...(typeof obj === "object" ? obj : {}),
            }),
          ),
        };
        setSectionData(transformed);
      } catch (error) {
        console.error("Failed to add package:", error);
      }
    },
    [newPackage, sectionData],
  );

  const handleNewPackageChange = useCallback(
    (envName: string, value: string) => {
      setNewPackage((prev) => ({ ...prev, [envName]: value }));
    },
    [],
  );

  const handleCreateEnvironment = useCallback(async () => {
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
      // Refresh data
      const info = await requestAPI<any>("project");
      const transformed = {
        ...sectionData,
        environments: Object.entries(info.environments || {}).map(
          ([name, obj]) => ({
            id: name,
            label: name,
            ...(typeof obj === "object" ? obj : {}),
          }),
        ),
      };
      setSectionData(transformed);
    } catch (error) {
      console.error("Failed to create environment:", error);
    }
  }, [sectionData]);

  const renderEnvironmentItem = useCallback(
    (item: SectionItem) => {
      const isExpanded = expandedEnvironments.has(item.id);
      const kind = item.kind || "unknown";
      const packages = item.packages || [];
      const showPackages =
        kind === "uv-venv" ||
        kind === "venv" ||
        kind === "python" ||
        kind === "julia" ||
        kind === "conda";

      return (
        <div key={item.id}>
          <div
            className="calkit-sidebar-item calkit-env-item"
            onClick={() => toggleEnvironment(item.id)}
            onContextMenu={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setEnvContextMenu({
                visible: true,
                x: e.clientX,
                y: e.clientY,
                env: item,
              });
            }}
          >
            <span className="calkit-sidebar-section-icon">
              {isExpanded ? "▼" : "▶"}
            </span>
            <span className="calkit-sidebar-item-label">{item.label}</span>
            <span className="calkit-env-actions">
              <button
                className="calkit-env-action-btn calkit-env-edit"
                title="Edit environment"
                onClick={(e) => {
                  e.stopPropagation();
                  (async () => {
                    const result = await showEnvironmentEditor({
                      mode: "edit",
                      initialName: item.id,
                      initialKind: kind,
                      initialPackages: packages,
                    });
                    if (!result) return;
                    try {
                      await requestAPI("environment/update", {
                        method: "POST",
                        body: JSON.stringify({
                          name: item.id,
                          kind: result.kind,
                          packages: result.packages,
                        }),
                      });
                      const info = await requestAPI<any>("project");
                      const transformed = {
                        ...sectionData,
                        environments: Object.entries(
                          info.environments || {},
                        ).map(([name, obj]) => ({
                          id: name,
                          label: name,
                          ...(typeof obj === "object" ? obj : {}),
                        })),
                      };
                      setSectionData(transformed);
                    } catch (error) {
                      console.error("Failed to update environment:", error);
                    }
                  })();
                }}
              >
                ✏️
              </button>
              <button
                className="calkit-env-action-btn calkit-env-delete"
                title="Delete environment"
                onClick={(e) => {
                  e.stopPropagation();
                  (async () => {
                    const confirm = await new Dialog({
                      title: `Delete environment '${item.id}'?`,
                      body: "This action cannot be undone.",
                      buttons: [
                        Dialog.cancelButton(),
                        Dialog.warnButton({ label: "Delete" }),
                      ],
                    }).launch();
                    if (!confirm.button.accept) return;
                    try {
                      await requestAPI("environment/delete", {
                        method: "POST",
                        body: JSON.stringify({ name: item.id }),
                      });
                      const info = await requestAPI<any>("project");
                      const transformed = {
                        ...sectionData,
                        environments: Object.entries(
                          info.environments || {},
                        ).map(([name, obj]) => ({
                          id: name,
                          label: name,
                          ...(typeof obj === "object" ? obj : {}),
                        })),
                      };
                      setSectionData(transformed);
                    } catch (error) {
                      console.error("Failed to delete environment:", error);
                    }
                  })();
                }}
              >
                🗑️
              </button>
            </span>
          </div>
          {isExpanded && (
            <div className="calkit-env-details">
              <div className="calkit-env-kind">
                <strong>Kind:</strong> {kind}
              </div>
              {showPackages && (
                <div className="calkit-env-packages">
                  <div className="calkit-env-packages-header">
                    <strong>Packages:</strong>
                  </div>
                  <div className="calkit-env-packages-list">
                    {packages.length === 0 && (
                      <div className="calkit-env-package-item">No packages</div>
                    )}
                    {packages.map((pkg: string, idx: number) => (
                      <div key={idx} className="calkit-env-package-item">
                        {pkg}
                      </div>
                    ))}
                  </div>
                  <div className="calkit-env-add-package">
                    <input
                      type="text"
                      className="calkit-env-package-input"
                      placeholder="Add package..."
                      value={newPackage[item.id] || ""}
                      onChange={(e) =>
                        handleNewPackageChange(item.id, e.target.value)
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleAddPackage(item.id);
                        }
                      }}
                    />
                    <button
                      className="calkit-env-add-button"
                      onClick={() => handleAddPackage(item.id)}
                      disabled={!newPackage[item.id]?.trim()}
                    >
                      +
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      );
    },
    [
      expandedEnvironments,
      newPackage,
      toggleEnvironment,
      handleAddPackage,
      handleNewPackageChange,
      sectionData,
    ],
  );

  const renderSection = useCallback(
    (sectionId: string, sectionLabel: string, icon: string) => {
      const isExpanded = expandedSections.has(sectionId);
      const items = sectionData[sectionId] || [];
      const showCreateButton = sectionId === "environments";

      return (
        <div key={sectionId} className="calkit-sidebar-section">
          <div
            className="calkit-sidebar-section-header"
            onClick={() => toggleSection(sectionId)}
            onContextMenu={(e) => {
              if (sectionId === "environments") {
                e.preventDefault();
                setEnvContextMenu({
                  visible: true,
                  x: e.clientX,
                  y: e.clientY,
                });
              }
            }}
          >
            <span className="calkit-sidebar-section-icon">
              {isExpanded ? "▼" : "▶"}
            </span>
            <span className="calkit-sidebar-section-label">{icon}</span>
            <span className="calkit-sidebar-section-title">{sectionLabel}</span>
            {showCreateButton && (
              <button
                className="calkit-sidebar-section-create"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCreateEnvironment();
                }}
                title="Create new environment"
              >
                +
              </button>
            )}
            <span className="calkit-sidebar-section-count">
              {items.length > 0 && `(${items.length})`}
            </span>
          </div>
          {isExpanded && items.length > 0 && (
            <div
              className="calkit-sidebar-section-content"
              onContextMenu={(e) => {
                if (sectionId === "environments") {
                  e.preventDefault();
                  setEnvContextMenu({
                    visible: true,
                    x: e.clientX,
                    y: e.clientY,
                  });
                }
              }}
            >
              {sectionId === "environments"
                ? items.map((item) => renderEnvironmentItem(item))
                : items.map((item) => (
                    <div key={item.id} className="calkit-sidebar-item">
                      <span className="calkit-sidebar-item-label">
                        {item.label}
                      </span>
                    </div>
                  ))}
            </div>
          )}
          {isExpanded && items.length === 0 && (
            <div className="calkit-sidebar-section-empty">No items found</div>
          )}
        </div>
      );
    },
    [
      expandedSections,
      sectionData,
      toggleSection,
      renderEnvironmentItem,
      handleCreateEnvironment,
    ],
  );

  if (loading) {
    return (
      <div className="calkit-sidebar">
        <div className="calkit-sidebar-header" />
        <div className="calkit-sidebar-content">
          <div className="calkit-sidebar-section-empty">Loading...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="calkit-sidebar">
      <div className="calkit-sidebar-header" />
      <div className="calkit-sidebar-content">
        {renderSection("environments", "Environments", "⚙️")}
        {renderSection("pipelineStages", "Pipeline", "🔄")}
        {renderSection("notebooks", "Notebooks", "📓")}
        {renderSection("figures", "Figures", "📊")}
        {renderSection("datasets", "Datasets", "📁")}
        {renderSection("questions", "Questions", "❓")}
        {renderSection("history", "History", "📜")}
        {renderSection("publications", "Publications", "📚")}
        {renderSection("notes", "Notes", "📝")}
        {renderSection("models", "Models", "🤖")}
      </div>
      {envContextMenu?.visible &&
        ReactDOM.createPortal(
          <div
            className="calkit-env-context-menu"
            style={{ left: envContextMenu.x, top: envContextMenu.y }}
          >
            {envContextMenu.env && (
              <>
                <div
                  className="calkit-env-context-item"
                  onClick={() => {
                    const env = envContextMenu.env!;
                    setEnvContextMenu(null);
                    (async () => {
                      const result = await showEnvironmentEditor({
                        mode: "edit",
                        initialName: env.id,
                        initialKind: env.kind || "unknown",
                        initialPackages: env.packages || [],
                      });
                      if (!result) return;
                      try {
                        await requestAPI("environment/update", {
                          method: "POST",
                          body: JSON.stringify({
                            name: env.id,
                            kind: result.kind,
                            packages: result.packages,
                          }),
                        });
                        const info = await requestAPI<any>("project");
                        const transformed = {
                          ...sectionData,
                          environments: Object.entries(
                            info.environments || {},
                          ).map(([name, obj]) => ({
                            id: name,
                            label: name,
                            ...(typeof obj === "object" ? obj : {}),
                          })),
                        };
                        setSectionData(transformed);
                      } catch (error) {
                        console.error("Failed to update environment:", error);
                      }
                    })();
                  }}
                >
                  Edit
                </div>
                <div
                  className="calkit-env-context-item calkit-danger"
                  onClick={() => {
                    const env = envContextMenu.env!;
                    setEnvContextMenu(null);
                    (async () => {
                      const confirm = await new Dialog({
                        title: `Delete environment '${env.id}'?`,
                        body: "This action cannot be undone.",
                        buttons: [
                          Dialog.cancelButton(),
                          Dialog.warnButton({ label: "Delete" }),
                        ],
                      }).launch();
                      if (!confirm.button.accept) return;
                      try {
                        await requestAPI("environment/delete", {
                          method: "POST",
                          body: JSON.stringify({ name: env.id }),
                        });
                        const info = await requestAPI<any>("project");
                        const transformed = {
                          ...sectionData,
                          environments: Object.entries(
                            info.environments || {},
                          ).map(([name, obj]) => ({
                            id: name,
                            label: name,
                            ...(typeof obj === "object" ? obj : {}),
                          })),
                        };
                        setSectionData(transformed);
                      } catch (error) {
                        console.error("Failed to delete environment:", error);
                      }
                    })();
                  }}
                >
                  Delete
                </div>
                <div className="calkit-env-context-separator" />
              </>
            )}
            <div
              className="calkit-env-context-item"
              onClick={() => {
                setEnvContextMenu(null);
                handleCreateEnvironment();
              }}
            >
              New environment
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
};

/**
 * A widget for the Calkit sidebar.
 */
export class CalkitSidebarWidget extends ReactWidget {
  constructor() {
    super();
    this.addClass("calkit-sidebar-widget");
  }

  render() {
    return <CalkitSidebar />;
  }
}
