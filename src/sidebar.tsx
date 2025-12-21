import React, { useCallback, useState } from "react";
import ReactDOM from "react-dom";
import { ReactWidget, Dialog } from "@jupyterlab/apputils";
import { requestAPI } from "./request";
import type { ISettingRegistry } from "@jupyterlab/settingregistry";
import type { IStateDB } from "@jupyterlab/statedb";
import { showEnvironmentEditor } from "./environment-editor";
import { showNotebookRegistration } from "./notebook-registration";
import { showProjectInfoEditor } from "./project-info-editor";
import { showCommitDialog } from "./commit-dialog";

interface SectionItem {
  id: string;
  label: string;
  [key: string]: any;
}

interface SectionDefinition {
  id: string;
  label: string;
  icon: string;
  /** Whether the section can be toggled in the settings dropdown. */
  toggleable?: boolean;
  /** Whether the section is visible by default when no user setting exists. */
  defaultVisible?: boolean;
}

const SECTION_DEFS: SectionDefinition[] = [
  { id: "basicInfo", label: "Basic info", icon: "ℹ️", toggleable: false },
  { id: "environments", label: "Environments", icon: "⚙️" },
  { id: "pipelineStages", label: "Pipeline", icon: "🔄" },
  { id: "notebooks", label: "Notebooks", icon: "📓" },
  { id: "figures", label: "Figures", icon: "📊", defaultVisible: false },
  { id: "datasets", label: "Datasets", icon: "📁" },
  { id: "questions", label: "Questions", icon: "❓" },
  { id: "history", label: "Save & sync", icon: "🔃", toggleable: false },
  {
    id: "publications",
    label: "Publications",
    icon: "📚",
    defaultVisible: false,
  },
  { id: "notes", label: "Notes", icon: "📝", defaultVisible: false },
  { id: "models", label: "Models", icon: "🤖", defaultVisible: false },
];

const DEFAULT_VISIBLE_SECTIONS = new Set(
  SECTION_DEFS.filter(
    (s) => s.toggleable !== false && s.defaultVisible !== false,
  ).map((s) => s.id),
);

/**
 * A sidebar component for Calkit JupyterLab extension.
 * Displays sections for environments, pipeline stages, notebooks, figures,
 * datasets, questions, history, publications, notes, and models.
 */
export interface CalkitSidebarProps {
  settings?: ISettingRegistry.ISettings | null;
  stateDB?: IStateDB | null;
}

export const CalkitSidebar: React.FC<CalkitSidebarProps> = ({
  settings,
  stateDB,
}) => {
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["basicInfo", "environments", "notebooks"]),
  );
  const [expandedEnvironments, setExpandedEnvironments] = useState<Set<string>>(
    new Set(),
  );
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
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
  const [notebookContextMenu, setNotebookContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
  } | null>(null);
  const [visibleSections, setVisibleSections] = useState<Set<string>>(
    new Set(DEFAULT_VISIBLE_SECTIONS),
  );
  const [showSettingsDropdown, setShowSettingsDropdown] = useState(false);
  const [projectInfo, setProjectInfo] = useState<{
    name: string;
    title: string;
    description: string;
    git_repo_url: string;
    owner: string;
  }>({ name: "", title: "", description: "", git_repo_url: "", owner: "" });

  const [gitStatus, setGitStatus] = useState<{
    changed: string[];
    staged: string[];
    untracked: string[];
    tracked: string[];
    sizes: Record<string, number>;
    ahead: number;
    behind: number;
    branch?: string | null;
    remote?: string | null;
  }>({
    changed: [],
    staged: [],
    untracked: [],
    tracked: [],
    sizes: {},
    ahead: 0,
    behind: 0,
    branch: null,
    remote: null,
  });
  const [gitSelections, setGitSelections] = useState<
    Record<string, { stage: boolean; storeInDvc: boolean }>
  >({});
  const [gitHistory, setGitHistory] = useState<
    Array<{ hash: string; message: string; author: string; date: string }>
  >([]);

  const SIZE_THRESHOLD = 5 * 1024 * 1024; // 5MB

  const fetchGitData = useCallback(async () => {
    try {
      const status = await requestAPI<any>("git/status");
      setGitStatus(status);
      const sel: Record<string, { stage: boolean; storeInDvc: boolean }> = {};
      [...(status.changed || []), ...(status.untracked || [])].forEach(
        (p: string) => {
          const isTracked = (status.tracked || []).includes(p);
          const size = status.sizes?.[p] ?? 0;
          const shouldDvc = !isTracked && size > SIZE_THRESHOLD;
          sel[p] = { stage: true, storeInDvc: shouldDvc };
        },
      );
      setGitSelections(sel);
      const history = await requestAPI<any>("git/history");
      setGitHistory(history.commits || []);
    } catch (err) {
      console.error("Failed to fetch git status/history:", err);
    }
  }, []);

  // Persist visible sections to localStorage
  React.useEffect(() => {
    // Initialize expandedSections from stateDB
    (async () => {
      try {
        if (stateDB) {
          const saved = (await stateDB.fetch("calkit:expandedSections")) as
            | string[]
            | null;
          if (saved && Array.isArray(saved)) {
            setExpandedSections(new Set(saved));
          }
        }
      } catch (e) {
        console.warn("Failed to fetch expandedSections from stateDB", e);
      }
    })();
  }, [stateDB]);

  React.useEffect(() => {
    // Initialize visibleSections from settings
    (async () => {
      try {
        const allowed = new Set(SECTION_DEFS.map((s) => s.id));
        const vs = (settings?.composite as any)?.visibleSections as
          | string[]
          | undefined;
        if (vs && Array.isArray(vs)) {
          const filtered = vs.filter((id) => allowed.has(id));
          setVisibleSections(
            filtered.length > 0
              ? new Set(filtered)
              : new Set(DEFAULT_VISIBLE_SECTIONS),
          );
        } else {
          setVisibleSections(new Set(DEFAULT_VISIBLE_SECTIONS));
        }
      } catch (e) {
        console.warn("Failed to initialize visibleSections from settings", e);
        setVisibleSections(new Set(DEFAULT_VISIBLE_SECTIONS));
      }
    })();
  }, [settings]);

  // Persist expanded sections via IStateDB
  React.useEffect(() => {
    (async () => {
      try {
        if (stateDB) {
          await stateDB.save("calkit:expandedSections", [...expandedSections]);
        }
      } catch (e) {
        console.warn("Failed to save expandedSections to stateDB", e);
      }
    })();
  }, [expandedSections, stateDB]);

  // Persist visible sections via ISettingRegistry
  React.useEffect(() => {
    (async () => {
      try {
        if (settings) {
          await settings.set("visibleSections", [...visibleSections]);
        }
      } catch (e) {
        console.warn("Failed to save visibleSections to settings", e);
      }
    })();
  }, [visibleSections, settings]);

  // Close context menu on outside click
  React.useEffect(() => {
    const handleClickOutside = () => {
      setEnvContextMenu(null);
      setNotebookContextMenu(null);
      setShowSettingsDropdown(false);
    };
    if (
      envContextMenu?.visible ||
      notebookContextMenu?.visible ||
      showSettingsDropdown
    ) {
      document.addEventListener("click", handleClickOutside);
      return () => {
        document.removeEventListener("click", handleClickOutside);
      };
    }
  }, [
    envContextMenu?.visible,
    notebookContextMenu?.visible,
    showSettingsDropdown,
  ]);

  // Periodically refresh git status/history
  React.useEffect(() => {
    const id = window.setInterval(() => {
      void fetchGitData();
    }, 30000);
    return () => {
      window.clearInterval(id);
    };
  }, [fetchGitData]);

  // Fetch sidebar data on mount
  React.useEffect(() => {
    const fetchSectionData = async () => {
      try {
        const info = await requestAPI<any>("project");
        // Populate project basic info; support both top-level and nested `project` shapes
        const pi = {
          name: info?.name ?? info?.project?.name ?? "",
          title: info?.title ?? info?.project?.title ?? "",
          description: info?.description ?? info?.project?.description ?? "",
          git_repo_url: info?.git_repo_url ?? info?.project?.git_repo_url ?? "",
          owner: info?.owner ?? info?.project?.owner ?? "",
        };
        setProjectInfo(pi);
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
    void fetchGitData();
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

  const toggleNotebook = useCallback((notebookId: string) => {
    setExpandedNotebooks((prev) => {
      const next = new Set(prev);
      if (next.has(notebookId)) {
        next.delete(notebookId);
      } else {
        next.add(notebookId);
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

  const handleSaveProjectInfo = useCallback(async () => {
    const result = await showProjectInfoEditor(projectInfo);
    if (!result) {
      return;
    }
    try {
      await requestAPI("project", {
        method: "PUT",
        body: JSON.stringify(result),
      });
      // Re-fetch after save to reflect any server-side normalization
      const info = await requestAPI<any>("project");
      const pi = {
        name: info?.name ?? info?.project?.name ?? "",
        title: info?.title ?? info?.project?.title ?? "",
        description: info?.description ?? info?.project?.description ?? "",
        git_repo_url: info?.git_repo_url ?? info?.project?.git_repo_url ?? "",
        owner: info?.owner ?? info?.project?.owner ?? "",
      };
      setProjectInfo(pi);
    } catch (error) {
      console.error("Failed to save project info:", error);
    }
  }, [projectInfo]);

  const handleCommit = useCallback(async () => {
    const trackedSet = new Set([...(gitStatus.tracked || [])]);
    const candidates = [
      ...(gitStatus.changed || []),
      ...(gitStatus.untracked || []),
    ];
    const files = candidates.map((path) => ({
      path,
      store_in_dvc: false,
      stage: true,
      tracked: trackedSet.has(path),
      size: gitStatus.sizes?.[path],
    }));
    const defaultMsg = files.length
      ? `Update ${files
          .map((f) => f.path)
          .slice(0, 5)
          .join(", ")}${files.length > 5 ? ", …" : ""}`
      : "Update project";
    const msg = await showCommitDialog(defaultMsg, files);
    if (!msg) return;
    const ignoreForever = msg.files.filter((f) => f.ignore_forever);
    const stagedFiles = msg.files.filter((f) => f.stage);
    if (ignoreForever.length > 0) {
      try {
        await requestAPI("git/ignore", {
          method: "POST",
          body: JSON.stringify({ paths: ignoreForever.map((f) => f.path) }),
        });
      } catch (e) {
        console.error("Failed to ignore paths:", e);
      }
    }
    if (stagedFiles.length === 0) return;
    try {
      await requestAPI("git/commit", {
        method: "POST",
        body: JSON.stringify({ message: msg.message, files: stagedFiles }),
      });
      if (msg.pushAfter) {
        try {
          await requestAPI("git/push", { method: "POST" });
        } catch (pushErr) {
          console.error("Push failed:", pushErr);
        }
      }
      await fetchGitData();
    } catch (err) {
      console.error("Commit failed:", err);
    }
  }, [
    fetchGitData,
    gitStatus.changed,
    gitStatus.sizes,
    gitStatus.tracked,
    gitStatus.untracked,
  ]);

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

  const handleCreateNotebook = useCallback(async () => {
    const environmentList = sectionData.environments || [];

    const createEnvironmentCallback = async (): Promise<string | null> => {
      const result = await showEnvironmentEditor({ mode: "create" });
      if (!result) {
        return null;
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
        // Refresh environments data
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
        return result.name;
      } catch (error) {
        console.error("Failed to create environment:", error);
        return null;
      }
    };

    const data = await showNotebookRegistration(
      "create",
      [],
      environmentList.map((env) => ({ id: env.id, label: env.label })),
      createEnvironmentCallback,
    );
    if (!data) {
      return;
    }
    try {
      await requestAPI("notebook/create", {
        method: "POST",
        body: JSON.stringify(data),
      });
      // Refresh data
      const info = await requestAPI<any>("project");
      const transformed = {
        ...sectionData,
        notebooks: Object.entries(info.notebooks || {}).map(([name, obj]) => ({
          id: name,
          label: name,
          ...(typeof obj === "object" ? obj : {}),
        })),
      };
      setSectionData(transformed);
    } catch (error) {
      console.error("Failed to create notebook:", error);
    }
  }, [sectionData]);

  const handleRegisterNotebook = useCallback(async () => {
    // TODO: Get list of existing notebooks from workspace
    const existingNotebooks: string[] = [];
    const data = await showNotebookRegistration("register", existingNotebooks);
    if (!data) {
      return;
    }
    try {
      await requestAPI("notebook/register", {
        method: "POST",
        body: JSON.stringify(data),
      });
      // Refresh data
      const info = await requestAPI<any>("project");
      const transformed = {
        ...sectionData,
        notebooks: Object.entries(info.notebooks || {}).map(([name, obj]) => ({
          id: name,
          label: name,
          ...(typeof obj === "object" ? obj : {}),
        })),
      };
      setSectionData(transformed);
    } catch (error) {
      console.error("Failed to register notebook:", error);
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
      handleNewPackageChange,
      handleAddPackage,
      sectionData,
    ],
  );

  const renderNotebookItem = useCallback(
    (item: SectionItem) => {
      const isExpanded = expandedNotebooks.has(item.id);
      const environment = item.environment || "";
      const inPipeline = item.in_pipeline || false;
      const environmentList = sectionData.environments || [];

      return (
        <div key={item.id}>
          <div
            className="calkit-sidebar-item calkit-notebook-item"
            onClick={() => toggleNotebook(item.id)}
          >
            <span className="calkit-sidebar-section-icon">
              {isExpanded ? "▼" : "▶"}
            </span>
            <span className="calkit-sidebar-item-label">{item.label}</span>
          </div>
          {isExpanded && (
            <div className="calkit-notebook-details">
              <div className="calkit-notebook-field">
                <label className="calkit-notebook-field-label">
                  Environment:
                </label>
                <select
                  className="calkit-notebook-env-select"
                  value={environment}
                  onChange={async (e) => {
                    const newEnv = e.target.value;
                    try {
                      await requestAPI("notebook/set-environment", {
                        method: "POST",
                        body: JSON.stringify({
                          notebook: item.id,
                          environment: newEnv,
                        }),
                      });
                      // Refresh data
                      const info = await requestAPI<any>("project");
                      const transformed = {
                        ...sectionData,
                        notebooks: Object.entries(info.notebooks || {}).map(
                          ([name, obj]) => ({
                            id: name,
                            label: name,
                            ...(typeof obj === "object" ? obj : {}),
                          }),
                        ),
                      };
                      setSectionData(transformed);
                    } catch (error) {
                      console.error(
                        "Failed to set notebook environment:",
                        error,
                      );
                    }
                  }}
                >
                  <option value="">None</option>
                  {environmentList.map((env) => (
                    <option key={env.id} value={env.id}>
                      {env.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="calkit-notebook-field">
                <label className="calkit-notebook-field-label">
                  <input
                    type="checkbox"
                    className="calkit-notebook-pipeline-checkbox"
                    checked={inPipeline}
                    onChange={async (e) => {
                      const checked = e.target.checked;
                      try {
                        await requestAPI("notebook/set-in-pipeline", {
                          method: "POST",
                          body: JSON.stringify({
                            notebook: item.id,
                            in_pipeline: checked,
                          }),
                        });
                        // Refresh data
                        const info = await requestAPI<any>("project");
                        const transformed = {
                          ...sectionData,
                          notebooks: Object.entries(info.notebooks || {}).map(
                            ([name, obj]) => ({
                              id: name,
                              label: name,
                              ...(typeof obj === "object" ? obj : {}),
                            }),
                          ),
                        };
                        setSectionData(transformed);
                      } catch (error) {
                        console.error(
                          "Failed to set notebook pipeline status:",
                          error,
                        );
                      }
                    }}
                  />
                  Include in pipeline
                </label>
              </div>
            </div>
          )}
        </div>
      );
    },
    [expandedNotebooks, toggleNotebook, sectionData],
  );

  const renderSection = useCallback(
    (sectionId: string, sectionLabel: string, icon: string) => {
      const isExpanded = expandedSections.has(sectionId);
      const items = sectionData[sectionId] || [];
      const showCreateButton =
        sectionId === "environments" || sectionId === "notebooks";
      const showEditButton = sectionId === "basicInfo";

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
              } else if (sectionId === "notebooks") {
                e.preventDefault();
                setNotebookContextMenu({
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
            {sectionId === "history" &&
              (() => {
                const newCount = (gitStatus.untracked || []).length;
                const modifiedSet = new Set([
                  ...(gitStatus.changed || []),
                  ...(gitStatus.staged || []),
                ]);
                const modifiedCount = modifiedSet.size;
                const pullCount = gitStatus.behind || 0;
                const hasChanges =
                  newCount > 0 || modifiedCount > 0 || pullCount > 0;
                return (
                  <span className="calkit-status-chips">
                    {newCount > 0 && (
                      <span
                        className="calkit-status-chip new"
                        title="New (untracked) files"
                      >
                        N: {newCount}
                      </span>
                    )}
                    {modifiedCount > 0 && (
                      <span
                        className="calkit-status-chip modified"
                        title="Modified files"
                      >
                        M: {modifiedCount}
                      </span>
                    )}
                    {pullCount > 0 && (
                      <span
                        className="calkit-status-chip pull"
                        title="Commits to pull"
                      >
                        P: {pullCount}
                      </span>
                    )}
                    {!hasChanges && (
                      <span className="calkit-status-chip clean">Clean</span>
                    )}
                  </span>
                );
              })()}
            {sectionId === "history" && (
              <button
                className="calkit-sidebar-section-save"
                title="Save/sync"
                onClick={(e) => {
                  e.stopPropagation();
                  handleCommit();
                }}
              >
                Save/sync
              </button>
            )}
            {showEditButton && (
              <button
                className="calkit-sidebar-section-edit"
                onClick={(e) => {
                  e.stopPropagation();
                  handleSaveProjectInfo();
                }}
                title="Edit project info"
              >
                ✏️
              </button>
            )}
            {showCreateButton && (
              <button
                className="calkit-sidebar-section-create"
                onClick={(e) => {
                  e.stopPropagation();
                  if (sectionId === "environments") {
                    handleCreateEnvironment();
                  } else if (sectionId === "notebooks") {
                    handleCreateNotebook();
                  }
                }}
                title={
                  sectionId === "environments"
                    ? "Create new environment"
                    : "Create new notebook"
                }
              >
                +
              </button>
            )}
            <span className="calkit-sidebar-section-count">
              {items.length > 0 && `(${items.length})`}
            </span>
          </div>
          {isExpanded && sectionId === "basicInfo" && (
            <div className="calkit-sidebar-section-content">
              <div className="calkit-basic-info-item">
                <span className="calkit-basic-info-label">Name:</span>
                <span className="calkit-basic-info-value">
                  {projectInfo.name || "—"}
                </span>
              </div>
              <div className="calkit-basic-info-item">
                <span className="calkit-basic-info-label">Title:</span>
                <span className="calkit-basic-info-value">
                  {projectInfo.title || "—"}
                </span>
              </div>
              <div className="calkit-basic-info-item">
                <span className="calkit-basic-info-label">Description:</span>
                <span className="calkit-basic-info-value">
                  {projectInfo.description || "—"}
                </span>
              </div>
              <div className="calkit-basic-info-item">
                <span className="calkit-basic-info-label">Git repo:</span>
                <span className="calkit-basic-info-value">
                  {projectInfo.git_repo_url ? (
                    /^https?:\/\//i.test(projectInfo.git_repo_url) ? (
                      <a
                        href={projectInfo.git_repo_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="calkit-basic-info-link"
                      >
                        {projectInfo.git_repo_url}
                      </a>
                    ) : (
                      projectInfo.git_repo_url
                    )
                  ) : (
                    "—"
                  )}
                </span>
              </div>
              <div className="calkit-basic-info-item">
                <span className="calkit-basic-info-label">Calkit URL:</span>
                <span className="calkit-basic-info-value">
                  {projectInfo.owner && projectInfo.name ? (
                    <a
                      href={`https://calkit.io/${projectInfo.owner}/${projectInfo.name}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="calkit-basic-info-link"
                    >
                      {`https://calkit.io/${projectInfo.owner}/${projectInfo.name}`}
                    </a>
                  ) : (
                    "—"
                  )}
                </span>
              </div>
            </div>
          )}
          {isExpanded && sectionId === "history" && (
            <div className="calkit-sidebar-section-content">
              <div className="calkit-git-actions">
                <button
                  className="calkit-sidebar-section-create"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCommit();
                  }}
                >
                  Save
                </button>
              </div>
              <div className="calkit-git-history">
                <div className="calkit-git-history-header">Recent history</div>
                {gitHistory.length === 0 && (
                  <div className="calkit-sidebar-section-empty">No history</div>
                )}
                {gitHistory.slice(0, 5).map((c) => (
                  <div key={c.hash} className="calkit-git-history-item">
                    <div className="calkit-git-history-message">
                      {c.message}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {isExpanded &&
            items.length > 0 &&
            sectionId !== "basicInfo" &&
            sectionId !== "history" && (
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
                  } else if (sectionId === "notebooks") {
                    e.preventDefault();
                    setNotebookContextMenu({
                      visible: true,
                      x: e.clientX,
                      y: e.clientY,
                    });
                  }
                }}
              >
                {sectionId === "environments"
                  ? items.map((item) => renderEnvironmentItem(item))
                  : sectionId === "notebooks"
                  ? items.map((item) => renderNotebookItem(item))
                  : items.map((item) => (
                      <div key={item.id} className="calkit-sidebar-item">
                        <span className="calkit-sidebar-item-label">
                          {item.label}
                        </span>
                      </div>
                    ))}
              </div>
            )}
          {isExpanded &&
            items.length === 0 &&
            sectionId !== "basicInfo" &&
            sectionId !== "history" && (
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
      renderNotebookItem,
      handleCreateEnvironment,
      handleCreateNotebook,
      projectInfo,
      handleSaveProjectInfo,
      gitStatus,
      gitSelections,
      gitHistory,
      handleCommit,
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
      <div className="calkit-sidebar-header">
        <div style={{ flex: 1 }} />
        <div className="calkit-sidebar-settings-container">
          <button
            className="calkit-sidebar-settings-btn"
            title="Show/hide categories"
            onClick={(e) => {
              e.stopPropagation();
              setShowSettingsDropdown(!showSettingsDropdown);
            }}
          >
            ⚙️
          </button>
          {showSettingsDropdown && (
            <div
              className="calkit-settings-dropdown"
              onClick={(e) => {
                e.stopPropagation();
              }}
            >
              {SECTION_DEFS.filter(
                (section) => section.toggleable !== false,
              ).map((section) => (
                <div
                  key={section.id}
                  className="calkit-settings-item"
                  onClick={(e) => {
                    e.stopPropagation();
                  }}
                >
                  <label
                    className="calkit-settings-checkbox-label"
                    onClick={(e) => {
                      e.stopPropagation();
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={visibleSections.has(section.id)}
                      onChange={(e) => {
                        const next = new Set(visibleSections);
                        if (e.target.checked) {
                          next.add(section.id);
                        } else {
                          next.delete(section.id);
                        }
                        setVisibleSections(next);
                      }}
                    />
                    {section.label}
                  </label>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="calkit-sidebar-content">
        {SECTION_DEFS.map((section) => {
          const isVisible =
            section.toggleable === false || visibleSections.has(section.id);
          if (!isVisible) {
            return null;
          }
          return renderSection(section.id, section.label, section.icon);
        })}
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
      {notebookContextMenu?.visible &&
        ReactDOM.createPortal(
          <div
            className="calkit-env-context-menu"
            style={{ left: notebookContextMenu.x, top: notebookContextMenu.y }}
          >
            <div
              className="calkit-env-context-item"
              onClick={() => {
                setNotebookContextMenu(null);
                handleCreateNotebook();
              }}
            >
              Create new notebook
            </div>
            <div
              className="calkit-env-context-item"
              onClick={() => {
                setNotebookContextMenu(null);
                handleRegisterNotebook();
              }}
            >
              Register existing notebook
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
  private _settings: ISettingRegistry.ISettings | null = null;
  private _stateDB: IStateDB | null = null;
  constructor() {
    super();
    this.addClass("calkit-sidebar-widget");
  }
  setSettings(settings: ISettingRegistry.ISettings) {
    this._settings = settings;
    this.update();
  }
  setStateDB(stateDB: IStateDB) {
    this._stateDB = stateDB;
    this.update();
  }

  render() {
    return <CalkitSidebar settings={this._settings} stateDB={this._stateDB} />;
  }
}
