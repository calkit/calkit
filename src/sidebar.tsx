import React, { useCallback, useState } from "react";
import { ReactWidget } from "@jupyterlab/apputils";
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

  // Fetch sidebar data on mount
  React.useEffect(() => {
    const fetchSectionData = async () => {
      try {
        const info = await requestAPI<any>("project");
        console.log("Fetched project info:", info);
        // Extract sections from project info and transform to array format
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
        console.log("Sidebar data loaded:", transformed);
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
          >
            <span className="calkit-sidebar-section-icon">
              {isExpanded ? "▼" : "▶"}
            </span>
            <span className="calkit-sidebar-item-label">{item.label}</span>
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
            <div className="calkit-sidebar-section-content">
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
          <div className="calkit-sidebar-section-empty">
            Loading... (sectionData keys: {Object.keys(sectionData).join(", ")})
          </div>
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
    </div>
  );
};

/**
 * A widget for the Calkit sidebar.
 */
export class CalkitSidebarWidget extends ReactWidget {
  constructor() {
    super();
    console.log("CalkitSidebarWidget constructor called");
    this.addClass("calkit-sidebar-widget");
  }

  render() {
    console.log("CalkitSidebarWidget render called");
    return <CalkitSidebar />;
  }
}
