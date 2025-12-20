import React, { useCallback, useState } from "react";
import { ReactWidget } from "@jupyterlab/apputils";
import { requestAPI } from "./request";

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
  const [sectionData, setSectionData] = useState<Record<string, SectionItem[]>>(
    {},
  );
  const [loading, setLoading] = useState(true);

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
          pipelineStages: Object.entries(info.pipeline || {}).map(
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
          datasets: Object.entries(info.datasets || {}).map(([name, obj]) => ({
            id: name,
            label: name,
            ...(typeof obj === "object" ? obj : {}),
          })),
          questions: Object.entries(info.questions || {}).map(
            ([name, obj]) => ({
              id: name,
              label: name,
              ...(typeof obj === "object" ? obj : {}),
            }),
          ),
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

  const renderSection = useCallback(
    (sectionId: string, sectionLabel: string, icon: string) => {
      const isExpanded = expandedSections.has(sectionId);
      const items = sectionData[sectionId] || [];

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
            <span className="calkit-sidebar-section-count">
              {items.length > 0 && `(${items.length})`}
            </span>
          </div>
          {isExpanded && items.length > 0 && (
            <div className="calkit-sidebar-section-content">
              {items.map((item) => (
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
    [expandedSections, sectionData, toggleSection],
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
        {renderSection("pipelineStages", "Pipeline Stages", "🔄")}
        {renderSection("notebooks", "Notebooks", "📓")}
        {renderSection("figures", "Figures", "📊")}
        {renderSection("datasets", "Datasets", "📁")}
        {renderSection("questions", "Questions", "❓")}
        {renderSection("history", "History (Git Commits)", "📜")}
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
