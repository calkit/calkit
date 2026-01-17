import React, { useCallback, useState } from "react";
import ReactDOM from "react-dom";
import { ReactWidget, Dialog } from "@jupyterlab/apputils";
import type { CommandRegistry } from "@lumino/commands";
import { launchIcon } from "@jupyterlab/ui-components";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactQueryDevtools } from "@tanstack/react-query-devtools";
import { queryClient } from "../queryClient";
import { requestAPI } from "../request";
import type { ISettingRegistry } from "@jupyterlab/settingregistry";
import type { IStateDB } from "@jupyterlab/statedb";
import {
  useProject,
  useGitStatus,
  useGitHistory,
  useCreateNotebook,
  useRegisterNotebook,
  useAddPackage,
  useCreateEnvironment,
  useCommit,
  usePush,
  useNotebooks,
  useEnvironments,
  useDeleteEnvironment,
  usePipelineStatus,
  useDependencies,
  useInstallDependency,
  type IDependencyItem,
  type IProjectInfo,
  type IGitStatus,
} from "../hooks/useQueries";
import { showEnvironmentEditor } from "./environment-editor";
import { showNotebookRegistration } from "./notebook-registration";
import { showProjectInfoEditor } from "./project-info-editor";
import { showCommitDialog } from "./commit-dialog";
import {
  showStageEditorDialog,
  STAGE_KIND_OPTIONS,
  type StageEditorResult,
} from "./stage-editor";
import { isFeatureEnabled } from "../feature-flags";
import { pipelineState } from "../pipeline-state";
import {
  generateProjectNameFromDir,
  generateProjectTitleFromDir,
  getDirNameFromPath,
} from "../utils/project-utils";

interface ISectionItem {
  id: string;
  label: string;
  [key: string]: any;
}

interface ISectionDefinition {
  id: string;
  label: string;
  icon: string;
  /** Whether the section can be toggled in the settings dropdown. */
  toggleable?: boolean;
  /** Whether the section is visible by default when no user setting exists. */
  defaultVisible?: boolean;
}

const SECTION_DEFS: ISectionDefinition[] = [
  { id: "basicInfo", label: "Basic info", icon: "ℹ️", toggleable: false },
  { id: "setup", label: "Setup", icon: "🛠️" },
  { id: "environments", label: "Environments", icon: "⚙️" },
  { id: "pipelineStages", label: "Pipeline", icon: "🔄" },
  { id: "notebooks", label: "Notebooks", icon: "📓" },
  { id: "figures", label: "Figures", icon: "📊", defaultVisible: false },
  { id: "datasets", label: "Datasets", icon: "📁" },
  { id: "questions", label: "Questions", icon: "❓" },
  { id: "history", label: "Save/sync", icon: "🔃", toggleable: false },
  {
    id: "publications",
    label: "Publications",
    icon: "📚",
    defaultVisible: false,
  },
  { id: "notes", label: "Notes", icon: "📝", defaultVisible: false },
  { id: "models", label: "Models", icon: "🤖", defaultVisible: false },
].filter((section) => {
  // Filter out sections based on feature flags
  const featureMap: Record<string, string> = {
    basicInfo: "basicInfo",
    setup: "setup",
    environments: "environments",
    pipelineStages: "pipelineStages",
    notebooks: "notebooks",
    figures: "figures",
    datasets: "datasets",
    questions: "questions",
    history: "history",
    publications: "publications",
    notes: "notes",
    models: "models",
  };
  const featureName = featureMap[section.id];
  return featureName
    ? isFeatureEnabled(
        featureName as keyof import("../feature-flags").IFeatureFlags,
      )
    : true;
});

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
export interface ICalkitSidebarProps {
  settings?: ISettingRegistry.ISettings | null;
  stateDB?: IStateDB | null;
  onStatusChange?: (needsAttention: boolean) => void;
  commands?: CommandRegistry;
  onSetExpandPipelineCallback?: (callback: () => void) => void;
}

export const CalkitSidebar: React.FC<ICalkitSidebarProps> = ({
  settings,
  stateDB,
  onStatusChange,
  commands,
  onSetExpandPipelineCallback,
}) => {
  // Query hooks - automatically manage data fetching and caching
  const projectQuery = useProject();
  const gitStatusQuery = useGitStatus();
  const pipelineStatusQuery = usePipelineStatus();
  const dependenciesQuery = useDependencies();
  const gitHistoryQuery = useGitHistory();
  const notebooksQuery = useNotebooks();
  const environmentsQuery = useEnvironments();

  // Mutation hooks - automatically invalidate related queries on success
  const createNotebookMutation = useCreateNotebook();
  const registerNotebookMutation = useRegisterNotebook();
  const addPackageMutation = useAddPackage();
  const installDependencyMutation = useInstallDependency();
  const createEnvironmentMutation = useCreateEnvironment();
  const commitMutation = useCommit();
  const pushMutation = usePush();
  const deleteEnvironmentMutation = useDeleteEnvironment();

  // Local UI state
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["setup", "basicInfo", "environments", "notebooks"]),
  );
  const [expandedEnvironments, setExpandedEnvironments] = useState<Set<string>>(
    new Set(),
  );
  const [expandedNotebooks, setExpandedNotebooks] = useState<Set<string>>(
    new Set(),
  );
  const [expandedStages, setExpandedStages] = useState<Set<string>>(new Set());
  const [newPackage, setNewPackage] = useState<Record<string, string>>({});
  const [installingDependency, setInstallingDependency] = useState<
    string | null
  >(null);
  const [envContextMenu, setEnvContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
    env?: ISectionItem;
  } | null>(null);
  const [notebookContextMenu, setNotebookContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
  } | null>(null);
  const [pipelineContextMenu, setPipelineContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
  } | null>(null);
  const [stageContextMenu, setStageContextMenu] = useState<{
    visible: boolean;
    x: number;
    y: number;
    stage?: ISectionItem;
  } | null>(null);
  const [visibleSections, setVisibleSections] = useState<Set<string>>(
    new Set(DEFAULT_VISIBLE_SECTIONS),
  );
  const [showSettingsDropdown, setShowSettingsDropdown] = useState(false);
  const [expandedGitSubsections, setExpandedGitSubsections] = useState<
    Set<string>
  >(new Set(["modified", "staged", "untracked", "history"]));
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  // Transform project data into section data, merging with environments data that includes packages
  const transformProjectData = useCallback(
    (
      info: IProjectInfo | undefined,
      environmentsData: Record<string, any> | undefined,
    ) => {
      if (!info) {
        return {
          setup: [] as IDependencyItem[],
          environments: [] as ISectionItem[],
          pipelineStages: [] as ISectionItem[],
          notebooks: [] as ISectionItem[],
          datasets: [] as ISectionItem[],
          questions: [] as ISectionItem[],
          models: [] as ISectionItem[],
          figures: [] as ISectionItem[],
          history: [] as ISectionItem[],
          publications: [] as ISectionItem[],
          notes: [] as ISectionItem[],
        };
      }

      return {
        setup: [] as IDependencyItem[],
        environments: Object.entries(info.environments || {}).map(
          ([name, obj]) => ({
            id: name,
            label: name,
            ...(typeof obj === "object" ? obj : {}),
            // Merge in packages from the environments API response if available
            ...(environmentsData?.[name]
              ? { packages: environmentsData[name].packages }
              : {}),
          }),
        ),
        pipelineStages: Object.entries(info.pipeline?.stages || {}).map(
          ([name, obj]) => ({
            id: name,
            label: name,
            ...(typeof obj === "object" ? obj : {}),
          }),
        ),
        notebooks: Array.isArray((info as any).notebooks)
          ? ((info as any).notebooks || []).map((nb: any) => ({
              id: nb?.path ?? nb?.id ?? nb?.name ?? "",
              label: nb?.path ?? nb?.name ?? "",
              ...(typeof nb === "object" ? nb : {}),
            }))
          : Object.entries((info as any).notebooks || {}).map(
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
    },
    [],
  );

  const sectionData = transformProjectData(
    projectQuery.data,
    environmentsQuery.data,
  );

  // Auto-expand basicInfo if project has no name
  React.useEffect(() => {
    if (!projectQuery.data?.name) {
      setExpandedSections((prev) => {
        const next = new Set(prev);
        next.add("basicInfo");
        return next;
      });
    }
  }, [projectQuery.data?.name]);

  if (dependenciesQuery.data) {
    sectionData.setup = dependenciesQuery.data as IDependencyItem[];
  } else {
    sectionData.setup = [];
  }

  // Override notebooks with enriched data from /notebooks endpoint that includes stage info
  if (notebooksQuery.data && Array.isArray(notebooksQuery.data)) {
    sectionData.notebooks = notebooksQuery.data.map((nb: any) => ({
      id: nb.path,
      label: nb.path,
      ...nb,
    }));
  }

  const projectInfo = projectQuery.data
    ? {
        name: projectQuery.data.name ?? "",
        title: projectQuery.data.title ?? "",
        description: projectQuery.data.description ?? "",
        git_repo_url: projectQuery.data.git_repo_url ?? "",
        owner: projectQuery.data.owner ?? "",
      }
    : {
        name: "",
        title: "",
        description: "",
        git_repo_url: "",
        owner: "",
      };

  const gitStatus: IGitStatus = gitStatusQuery.data || {
    changed: [],
    staged: [],
    untracked: [],
    tracked: [],
    sizes: {},
    ahead: 0,
    behind: 0,
    branch: null,
    remote: null,
  };

  const pipelineStatus = pipelineStatusQuery.data;
  const hasPipelineIssues = Boolean(
    pipelineStatus?.is_outdated ||
      (pipelineStatus?.pipeline &&
        Object.keys(pipelineStatus.pipeline || {}).length > 0),
  );
  const hasGitChanges =
    (gitStatus.changed?.length || 0) > 0 ||
    (gitStatus.untracked?.length || 0) > 0 ||
    (gitStatus.staged?.length || 0) > 0;
  const dependenciesList = (sectionData.setup || []) as IDependencyItem[];
  const outstandingDependencies = dependenciesList.filter((dep) => {
    if (dep.required === false) {
      return false;
    }
    const status = (dep.status || "").toLowerCase();
    const isHealthy =
      status === "ok" ||
      status === "ready" ||
      status === "installed" ||
      dep.installed === true;
    const missingEnv = dep.env_var ? !dep.value : false;
    const missing =
      dep.installed === false ||
      dep.configured === false ||
      Boolean(dep.missing_reason) ||
      missingEnv;
    return missing || !isHealthy;
  });
  const outstandingSetupCount = outstandingDependencies.length;
  const needsAttention =
    hasPipelineIssues || hasGitChanges || outstandingSetupCount > 0;

  React.useEffect(() => {
    onStatusChange?.(needsAttention);
  }, [needsAttention, onStatusChange]);

  // Set up callback to expand pipeline section
  React.useEffect(() => {
    if (onSetExpandPipelineCallback) {
      onSetExpandPipelineCallback(() => {
        setExpandedSections((prev) => {
          const next = new Set(prev);
          next.add("pipelineStages");
          return next;
        });
      });
    }
  }, [onSetExpandPipelineCallback]);

  // Convert git status to selections
  const gitSelections: Record<string, { stage: boolean; storeInDvc: boolean }> =
    {};
  const SIZE_THRESHOLD = 5 * 1024 * 1024; // 5MB
  [...(gitStatus.changed || []), ...(gitStatus.untracked || [])].forEach(
    (p: string) => {
      const isTracked = (gitStatus.tracked || []).includes(p);
      const size = gitStatus.sizes?.[p] ?? 0;
      const shouldDvc = !isTracked && size > SIZE_THRESHOLD;
      gitSelections[p] = { stage: true, storeInDvc: shouldDvc };
    },
  );

  const gitHistory = gitHistoryQuery.data?.commits || [];

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

  const toggleStage = useCallback((stageId: string) => {
    setExpandedStages((prev) => {
      const next = new Set(prev);
      if (next.has(stageId)) {
        next.delete(stageId);
      } else {
        next.add(stageId);
      }
      return next;
    });
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
      setPipelineContextMenu(null);
      setStageContextMenu(null);
      setShowSettingsDropdown(false);
    };
    if (
      envContextMenu?.visible ||
      notebookContextMenu?.visible ||
      pipelineContextMenu?.visible ||
      stageContextMenu?.visible ||
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
    pipelineContextMenu?.visible,
    stageContextMenu?.visible,
    showSettingsDropdown,
  ]);

  const handleAddPackage = useCallback(
    async (envName: string) => {
      const packageName = newPackage[envName];
      if (!packageName?.trim()) {
        return;
      }
      try {
        await addPackageMutation.mutateAsync({
          environment: envName,
          package: packageName.trim(),
        });
        // Clear input after successful mutation
        setNewPackage((prev) => ({ ...prev, [envName]: "" }));
      } catch (error) {
        console.error("Failed to add package:", error);
      }
    },
    [newPackage, addPackageMutation],
  );

  const handleInstallDependency = useCallback(
    async (dep: IDependencyItem) => {
      if (!dep.installable) {
        return;
      }
      setInstallingDependency(dep.name);
      try {
        await installDependencyMutation.mutateAsync(dep.name);
      } catch (error) {
        console.error("Failed to install dependency:", error);
      } finally {
        setInstallingDependency(null);
      }
    },
    [installDependencyMutation],
  );

  const handleNewPackageChange = useCallback(
    (envName: string, value: string) => {
      setNewPackage((prev) => ({ ...prev, [envName]: value }));
    },
    [],
  );

  /**
   * Check if project has a name, and if not, prompt user to set one
   * @returns true if project has a name (or user just set one), false if user cancelled
   */
  const ensureProjectName = useCallback(async (): Promise<boolean> => {
    if (projectQuery.data?.name) {
      return true;
    }

    // Get current directory to generate suggestions
    try {
      const cwd = await requestAPI<{ cwd: string }>("system");
      const dirName = getDirNameFromPath(cwd.cwd);

      const suggestedName = generateProjectNameFromDir(dirName);
      const suggestedTitle = generateProjectTitleFromDir(dirName);

      // Use the project info editor with suggested values
      const result = await showProjectInfoEditor({
        name: suggestedName,
        title: suggestedTitle,
        description: projectInfo.description || "",
        git_repo_url: projectInfo.git_repo_url || "",
        owner: projectInfo.owner || "",
      });

      if (!result) {
        return false;
      }

      // Update project with the name and title
      await requestAPI("project", {
        method: "PUT",
        body: JSON.stringify(result),
      });

      // Invalidate project query to refetch updated data
      await queryClient.invalidateQueries({ queryKey: ["project"] });

      return true;
    } catch (error) {
      console.error("Failed to ensure project name:", error);
      return false;
    }
  }, [projectQuery.data?.name, projectInfo]);

  const handleSaveProjectInfo = useCallback(async () => {
    // If project has no name, suggest the current directory name
    let suggestedInfo = { ...projectInfo };
    if (!suggestedInfo.name) {
      try {
        const cwd = await requestAPI<{ cwd: string }>("system");
        if (cwd && cwd.cwd) {
          // Extract basename from path
          const dirName = cwd.cwd.split("/").filter(Boolean).pop() || "";
          suggestedInfo.name = dirName;
        }
      } catch (error) {
        console.warn("Failed to get current directory:", error);
      }
    }

    const result = await showProjectInfoEditor(suggestedInfo);
    if (!result) {
      return;
    }
    try {
      await requestAPI("project", {
        method: "PUT",
        body: JSON.stringify(result),
      });
      // Invalidate project query to refetch updated data
      await queryClient.invalidateQueries({ queryKey: ["project"] });
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
    if (!msg) {
      return;
    }
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
    if (stagedFiles.length === 0) {
      return;
    }
    try {
      await commitMutation.mutateAsync({
        message: msg.message,
        files: stagedFiles,
      });
      if (msg.pushAfter) {
        try {
          await pushMutation.mutateAsync();
        } catch (pushErr) {
          console.error("Push failed:", pushErr);
        }
      }
    } catch (err) {
      console.error("Commit failed:", err);
    }
  }, [
    gitStatus.changed,
    gitStatus.sizes,
    gitStatus.tracked,
    gitStatus.untracked,
    commitMutation,
    pushMutation,
  ]);

  const handleRunPipeline = useCallback(async () => {
    setPipelineRunning(true);
    setPipelineError(null);
    pipelineState.setRunning(true, "Running pipeline...");
    try {
      await requestAPI("pipeline/runs", {
        method: "POST",
        body: JSON.stringify({ targets: [] }),
      });
      // Refetch pipeline status immediately and wait for it to complete
      await queryClient.refetchQueries({ queryKey: ["pipelineStatus"] });
      // Also refresh project data
      await queryClient.invalidateQueries({ queryKey: ["project"] });
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      setPipelineError(errorMsg);
      console.error("Failed to run pipeline:", error);
    } finally {
      setPipelineRunning(false);
      pipelineState.setRunning(false);
    }
  }, []);

  const handleRunStage = useCallback(async (stageName: string) => {
    if (!stageName) return;
    pipelineState.setRunning(true, `Running stage: ${stageName}`);
    try {
      await requestAPI("pipeline/runs", {
        method: "POST",
        body: JSON.stringify({ targets: [stageName] }),
      });
      await queryClient.invalidateQueries({ queryKey: ["project"] });
      await queryClient.invalidateQueries({ queryKey: ["pipelineStatus"] });
    } catch (error) {
      console.error("Failed to run stage:", error);
    } finally {
      pipelineState.setRunning(false);
    }
  }, []);

  const handleCreateStage = useCallback(async () => {
    const hasName = await ensureProjectName();
    if (!hasName) {
      return;
    }

    await showStageEditorDialog({
      title: "Create new stage",
      kind: STAGE_KIND_OPTIONS[0].value,
      environment: "",
      inputs: [],
      outputs: [],
      attributes: {},
      onSave: async ({
        name,
        inputs,
        outputs,
        kind,
        environment,
        attributes,
      }: StageEditorResult) => {
        if (!name.trim()) return;
        try {
          await requestAPI("pipeline/stage", {
            method: "PUT",
            body: JSON.stringify({
              name,
              kind,
              environment,
              inputs,
              outputs,
              ...attributes,
            }),
          });
          await queryClient.invalidateQueries({ queryKey: ["project"] });
          await queryClient.invalidateQueries({ queryKey: ["pipelineStatus"] });
        } catch (error) {
          console.error("Failed to create stage:", error);
        }
      },
    });
  }, [ensureProjectName]);

  const handleCreateEnvironment = useCallback(async () => {
    const hasName = await ensureProjectName();
    if (!hasName) {
      return;
    }

    await showEnvironmentEditor({
      mode: "create",
      onSubmit: async ({ name, kind, path, packages }) => {
        try {
          await requestAPI("environments", {
            method: "POST",
            body: JSON.stringify({ name, kind, path, packages }),
          });
          await queryClient.invalidateQueries({ queryKey: ["environments"] });
          await queryClient.invalidateQueries({ queryKey: ["project"] });
        } catch (error) {
          console.error("Failed to create environment:", error);
          throw error;
        }
      },
    });
  }, [ensureProjectName]);

  const handleCreateNotebook = useCallback(async () => {
    const hasName = await ensureProjectName();
    if (!hasName) {
      return;
    }

    const environmentList = sectionData.environments || [];

    const createEnvironmentCallback = async (): Promise<string | null> => {
      let createdName: string | null = null;
      await showEnvironmentEditor({
        mode: "create",
        onSubmit: async ({ name, kind, path, packages }) => {
          try {
            await requestAPI("environments", {
              method: "POST",
              body: JSON.stringify({ name, kind, path, packages }),
            });
            await queryClient.invalidateQueries({ queryKey: ["environments"] });
            await queryClient.invalidateQueries({ queryKey: ["project"] });
            createdName = name;
          } catch (error) {
            console.error("Failed to create environment:", error);
            throw error;
          }
        },
      });
      return createdName;
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
      await createNotebookMutation.mutateAsync(data);
    } catch (error) {
      console.error("Failed to create notebook:", error);
    }
  }, [
    sectionData.environments,
    createNotebookMutation,
    createEnvironmentMutation,
    ensureProjectName,
  ]);

  const handleRegisterNotebook = useCallback(async () => {
    // TODO: Get list of existing notebooks from workspace
    const existingNotebooks: string[] = [];
    const data = await showNotebookRegistration("register", existingNotebooks);
    if (!data) {
      return;
    }
    try {
      await registerNotebookMutation.mutateAsync(data);
    } catch (error) {
      console.error("Failed to register notebook:", error);
    }
  }, [registerNotebookMutation]);

  const renderEnvironmentItem = useCallback(
    (item: ISectionItem) => {
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
              <div className="calkit-env-actions">
                <button
                  className="calkit-env-action-btn calkit-env-edit"
                  title="Edit environment"
                  onClick={(e) => {
                    e.stopPropagation();
                    (async () => {
                      await showEnvironmentEditor({
                        mode: "edit",
                        initialName: item.id,
                        initialKind: kind,
                        initialPath: item.path,
                        initialPackages: packages,
                        onSubmit: async ({ name, kind, path, packages }) => {
                          try {
                            await requestAPI("environments", {
                              method: "POST",
                              body: JSON.stringify({
                                name,
                                kind,
                                path,
                                packages,
                              }),
                            });
                          } catch (error) {
                            console.error(
                              "Failed to update environment:",
                              error,
                            );
                            throw error;
                          }
                        },
                      });
                    })();
                  }}
                >
                  ✏️ Edit
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
                      if (!confirm.button.accept) {
                        return;
                      }
                      try {
                        await deleteEnvironmentMutation.mutateAsync(item.id);
                      } catch (error) {
                        console.error("Failed to delete environment:", error);
                      }
                    })();
                  }}
                >
                  🗑️ Delete
                </button>
              </div>
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

  const renderPipelineStage = useCallback(
    (stage: ISectionItem) => {
      const isStageExpanded = expandedStages.has(stage.id);
      const kind = stage.kind || "unknown";
      const inputs: string[] = stage.inputs || [];
      const outputs: string[] = stage.outputs || [];
      const environment = stage.environment || "";
      const baseStageKeys = new Set([
        "id",
        "label",
        "kind",
        "inputs",
        "outputs",
        "environment",
      ]);
      const attributes = Object.keys(stage || {}).reduce(
        (acc: Record<string, any>, key) => {
          if (!baseStageKeys.has(key)) {
            acc[key] = (stage as any)[key];
          }
          return acc;
        },
        {},
      );
      const staleStages = pipelineStatus?.stale_stages || {};
      let isStale = stage.id in staleStages;

      if (!isStale) {
        const stageInfo = pipelineStatus?.pipeline?.stages?.[stage.id];
        if (stageInfo) {
          isStale = Boolean(
            stageInfo.is_stale ||
              stageInfo.is_outdated ||
              stageInfo.outdated ||
              stageInfo.needs_run,
          );
        }
      }

      return (
        <div key={stage.id}>
          <div
            className={`calkit-sidebar-item calkit-stage-item${
              isStale ? " stale" : ""
            }`}
            onClick={() => toggleStage(stage.id)}
          >
            <span className="calkit-sidebar-section-icon">
              {isStageExpanded ? "▼" : "▶"}
            </span>
            <span className="calkit-sidebar-item-label">
              {stage.label || stage.id}
            </span>
          </div>
          {isStageExpanded && (
            <div className="calkit-env-details">
              <div className="calkit-env-actions">
                <button
                  className="calkit-env-action-btn calkit-env-edit"
                  title="Edit stage"
                  onClick={(e) => {
                    e.stopPropagation();
                    (async () => {
                      await showStageEditorDialog({
                        title: `Edit stage '${stage.id}'`,
                        stageName: stage.id,
                        inputs: inputs,
                        outputs: outputs,
                        kind: kind,
                        environment: environment,
                        attributes,
                        onSave: async ({
                          name,
                          inputs: newInputs,
                          outputs: newOutputs,
                          kind: newKind,
                          environment: newEnvironment,
                          attributes: newAttributes,
                        }: StageEditorResult) => {
                          try {
                            await requestAPI("pipeline/stage", {
                              method: "PUT",
                              body: JSON.stringify({
                                current_stage_name: stage.id,
                                name: name,
                                environment: newEnvironment,
                                kind: newKind,
                                inputs: newInputs,
                                outputs: newOutputs,
                                ...newAttributes,
                              }),
                            });
                            await queryClient.invalidateQueries({
                              queryKey: ["project"],
                            });
                            await queryClient.invalidateQueries({
                              queryKey: ["pipelineStatus"],
                            });
                          } catch (err) {
                            console.error("Failed to update stage:", err);
                          }
                        },
                      });
                    })();
                  }}
                >
                  ✏️ Edit
                </button>
                <button
                  className="calkit-env-action-btn calkit-env-delete"
                  title="Delete stage"
                  onClick={async (e) => {
                    e.stopPropagation();
                    const confirm = await new Dialog({
                      title: `Delete stage '${stage.id}'?`,
                      body: "This action cannot be undone.",
                      buttons: [
                        Dialog.cancelButton(),
                        Dialog.warnButton({ label: "Delete" }),
                      ],
                    }).launch();
                    if (!confirm.button.accept) return;
                    try {
                      await requestAPI("pipeline/stages", {
                        method: "DELETE",
                        body: JSON.stringify({
                          name: stage.id,
                        }),
                      });
                      await queryClient.invalidateQueries({
                        queryKey: ["project"],
                      });
                      await queryClient.invalidateQueries({
                        queryKey: ["pipelineStatus"],
                      });
                    } catch (err) {
                      console.error("Failed to delete stage:", err);
                    }
                  }}
                >
                  🗑️ Delete
                </button>
              </div>
              <div className="calkit-env-kind">
                <strong>Kind:</strong> {kind}
              </div>
              <div className="calkit-env-kind">
                <strong>Environment:</strong> {environment || "—"}
              </div>
              <div className="calkit-env-packages">
                <div className="calkit-env-packages-header">
                  <strong>Inputs:</strong>
                </div>
                <div className="calkit-env-packages-list">
                  {inputs.length === 0 && (
                    <div className="calkit-env-package-item">None</div>
                  )}
                  {inputs.map((inp: string, idx: number) => (
                    <div key={idx} className="calkit-env-package-item">
                      {inp}
                    </div>
                  ))}
                </div>
              </div>
              <div className="calkit-env-packages">
                <div className="calkit-env-packages-header">
                  <strong>Outputs:</strong>
                </div>
                <div className="calkit-env-packages-list">
                  {outputs.length === 0 && (
                    <div className="calkit-env-package-item">None</div>
                  )}
                  {outputs.map((outp: string, idx: number) => (
                    <div key={idx} className="calkit-env-package-item">
                      {outp}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>
      );
    },
    [expandedStages, toggleStage, pipelineStatus, queryClient],
  );

  const renderNotebookItem = useCallback(
    (item: ISectionItem) => {
      const isExpanded = expandedNotebooks.has(item.id);
      // Extract environment name - it could be a string or an object with a "name" property
      let environment = "";
      if (typeof item.environment === "string") {
        environment = item.environment;
      } else if (item.environment && typeof item.environment === "object") {
        environment = (item.environment as any).name || "";
      }
      const stageName = (item.stage as any)?.name || "";
      const environmentList = sectionData.environments || [];

      const handleOpenNotebook = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (commands) {
          commands.execute("docmanager:open", { path: item.id });
        }
      };

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
            <button
              className="calkit-notebook-open-btn"
              onClick={handleOpenNotebook}
              title="Open notebook"
            >
              <launchIcon.react tag="span" />
            </button>
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
                      // Invalidate project query to refetch
                      await queryClient.invalidateQueries({
                        queryKey: ["project"],
                      });
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
                  Pipeline stage:
                </label>
                <div className="calkit-notebook-pipeline-controls">
                  <input
                    type="text"
                    className="calkit-notebook-pipeline-input"
                    placeholder="Not in pipeline"
                    value={stageName}
                    onChange={async (e) => {
                      const stageName = e.target.value;
                      if (stageName.trim()) {
                        try {
                          // Use the NotebookStageRouteHandler to set the notebook's stage
                          await requestAPI("notebook/stage", {
                            method: "PUT",
                            body: JSON.stringify({
                              path: item.id,
                              stage_name: stageName,
                              environment: "",
                              inputs: [],
                              outputs: [],
                            }),
                          });
                          // Invalidate queries to refetch
                          await queryClient.invalidateQueries({
                            queryKey: ["project"],
                          });
                          await queryClient.invalidateQueries({
                            queryKey: ["pipelineStatus"],
                          });
                        } catch (error) {
                          console.error("Failed to set notebook stage:", error);
                        }
                      }
                    }}
                  />
                  {!stageName && (
                    <button
                      className="calkit-notebook-create-stage-btn"
                      title="Create new stage"
                      onClick={(e) => {
                        e.stopPropagation();
                        (async () => {
                          await showStageEditorDialog({
                            title: "Create new stage",
                            kind: "jupyter-notebook",
                            environment: environment,
                            inputs: [],
                            outputs: [],
                            attributes: {},
                            onSave: async ({
                              name: stageName,
                              inputs,
                              outputs,
                              kind,
                              environment,
                              attributes,
                            }: StageEditorResult) => {
                              if (!stageName.trim()) return;
                              try {
                                // Create the stage by setting it on the notebook
                                await requestAPI("notebook/stage", {
                                  method: "PUT",
                                  body: JSON.stringify({
                                    path: item.id,
                                    stage_name: stageName,
                                    environment: environment,
                                    inputs: inputs,
                                    outputs: outputs,
                                    kind: kind,
                                    ...attributes,
                                  }),
                                });
                                await queryClient.invalidateQueries({
                                  queryKey: ["project"],
                                });
                                await queryClient.invalidateQueries({
                                  queryKey: ["pipelineStatus"],
                                });
                              } catch (err) {
                                console.error("Failed to create stage:", err);
                              }
                            },
                          });
                        })();
                      }}
                    >
                      +
                    </button>
                  )}
                  {stageName && (
                    <button
                      className="calkit-notebook-edit-stage-btn"
                      title="Edit stage inputs/outputs"
                      onClick={(e) => {
                        e.stopPropagation();
                        (async () => {
                          const stageData = (item.stage as any) || {};
                          const baseStageKeys = new Set([
                            "name",
                            "kind",
                            "inputs",
                            "outputs",
                            "environment",
                          ]);
                          const attributes = Object.keys(
                            stageData || {},
                          ).reduce((acc: Record<string, any>, key) => {
                            if (!baseStageKeys.has(key)) {
                              acc[key] = (stageData as any)[key];
                            }
                            return acc;
                          }, {});
                          await showStageEditorDialog({
                            title: `Edit stage '${stageName}'`,
                            stageName: stageName,
                            kind: stageData.kind || "jupyter-notebook",
                            environment: stageData.environment || environment,
                            inputs: stageData.inputs || [],
                            outputs: stageData.outputs || [],
                            attributes,
                            onSave: async ({
                              name,
                              inputs,
                              outputs,
                              kind,
                              environment,
                              attributes,
                            }: StageEditorResult) => {
                              try {
                                // Update the stage with the new inputs/outputs
                                await requestAPI("notebook/stage", {
                                  method: "PUT",
                                  body: JSON.stringify({
                                    path: item.id,
                                    stage_name: name,
                                    environment: environment,
                                    inputs: inputs,
                                    outputs: outputs,
                                    kind: kind,
                                    ...attributes,
                                  }),
                                });
                                await queryClient.invalidateQueries({
                                  queryKey: ["project"],
                                });
                                await queryClient.invalidateQueries({
                                  queryKey: ["pipelineStatus"],
                                });
                              } catch (err) {
                                console.error("Failed to update stage:", err);
                              }
                            },
                          });
                        })();
                      }}
                    >
                      ✏️ Edit
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      );
    },
    [expandedNotebooks, toggleNotebook, sectionData, commands],
  );

  const renderSection = useCallback(
    (sectionId: string, sectionLabel: string, icon: string) => {
      const isExpanded = expandedSections.has(sectionId);
      let items: ISectionItem[] =
        sectionData[sectionId as keyof typeof sectionData] || [];
      // Fallback: populate notebooks from discovery when project has none
      if (
        sectionId === "notebooks" &&
        (!items || items.length === 0) &&
        notebooksQuery.data
      ) {
        items = (notebooksQuery.data || []).map((nb: any) => ({
          id: nb.path,
          label: nb.path,
          in_pipeline: !!nb.stage,
        }));
      }
      const showCreateButton =
        sectionId === "environments" ||
        sectionId === "notebooks" ||
        sectionId === "pipelineStages";
      const showEditButton = sectionId === "basicInfo";
      const newCount =
        sectionId === "history"
          ? (gitStatus.untracked || []).length
          : sectionId === "setup"
          ? outstandingSetupCount
          : 0;
      const modifiedCount =
        sectionId === "history"
          ? new Set([...(gitStatus.changed || []), ...(gitStatus.staged || [])])
              .size
          : 0;
      const pullCount = sectionId === "history" ? gitStatus.behind || 0 : 0;
      const hasChanges = newCount > 0 || modifiedCount > 0 || pullCount > 0;
      const saveIcon = pullCount > 0 ? "⬇️" : "💾";
      const saveTitle = pullCount > 0 ? "Pull changes" : "Save";

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
              } else if (sectionId === "pipelineStages") {
                e.preventDefault();
                setPipelineContextMenu({
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
            {sectionId === "history" && (
              <button
                className={`calkit-sidebar-section-save${
                  hasChanges ? " has-changes" : ""
                }`}
                title={saveTitle}
                onClick={(e) => {
                  e.stopPropagation();
                  handleCommit();
                }}
              >
                {saveIcon}
              </button>
            )}
            {sectionId === "history" && hasChanges && (
              <span className="calkit-status-chips">
                {newCount > 0 && (
                  <span
                    className="calkit-status-chip new"
                    title={`New (untracked) files: ${newCount}`}
                  >
                    {newCount}
                  </span>
                )}
                {modifiedCount > 0 && (
                  <span
                    className="calkit-status-chip modified"
                    title={`Modified files: ${modifiedCount}`}
                  >
                    {modifiedCount}
                  </span>
                )}
                {pullCount > 0 && (
                  <span
                    className="calkit-status-chip pull"
                    title={`Commits to pull: ${pullCount}`}
                  >
                    {pullCount}
                  </span>
                )}
              </span>
            )}
            {sectionId === "setup" && newCount > 0 && (
              <span className="calkit-status-chips">
                <span
                  className="calkit-status-chip stale"
                  title={`${newCount} setup item${
                    newCount === 1 ? "" : "s"
                  } need attention`}
                >
                  {newCount}
                </span>
              </span>
            )}
            {sectionId === "basicInfo" && !projectQuery.data?.name && (
              <span className="calkit-status-chips">
                <span
                  className="calkit-status-chip missing"
                  title="Project name is required"
                >
                  ⚠
                </span>
              </span>
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
                  } else if (sectionId === "pipelineStages") {
                    handleCreateStage();
                  }
                }}
                title={
                  sectionId === "environments"
                    ? "Create new environment"
                    : sectionId === "notebooks"
                    ? "Create new notebook"
                    : "Create new stage"
                }
              >
                +
              </button>
            )}
            {sectionId === "pipelineStages" &&
              (() => {
                const ps: any = pipelineStatus;
                let outdatedCount = 0;
                if (ps) {
                  // Check for stale_stages object (new format)
                  if (ps?.stale_stages && typeof ps.stale_stages === "object") {
                    outdatedCount = Object.keys(ps.stale_stages).length;
                  } else if (typeof ps?.stages_outdated_count === "number") {
                    outdatedCount = ps.stages_outdated_count;
                  } else if (Array.isArray(ps?.outdated_stages)) {
                    outdatedCount = ps.outdated_stages.length;
                  } else if (
                    ps?.pipeline?.stages &&
                    typeof ps.pipeline.stages === "object"
                  ) {
                    outdatedCount = Object.values(ps.pipeline.stages).filter(
                      (s: any) => s?.is_outdated || s?.outdated || s?.needs_run,
                    ).length;
                  }
                }
                const hasStaleStages = outdatedCount > 0;
                return (
                  <>
                    {sectionId === "pipelineStages" && (
                      <button
                        className={`calkit-sidebar-section-run${
                          pipelineRunning ? " running" : ""
                        }${hasStaleStages ? " stale" : ""}`}
                        title={
                          pipelineRunning
                            ? "Pipeline running..."
                            : "Run pipeline"
                        }
                        onClick={(e) => {
                          e.stopPropagation();
                          if (!pipelineRunning) {
                            handleRunPipeline();
                          }
                        }}
                        disabled={pipelineRunning}
                      >
                        {pipelineRunning ? (
                          <span className="calkit-spinner" />
                        ) : (
                          "▶"
                        )}
                      </button>
                    )}
                    {outdatedCount > 0 && (
                      <span
                        className="calkit-status-chip stale"
                        title={`${outdatedCount} stage${
                          outdatedCount === 1 ? "" : "s"
                        } out of date`}
                      >
                        {outdatedCount}
                      </span>
                    )}
                  </>
                );
              })()}
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
          {isExpanded && sectionId === "setup" && (
            <div className="calkit-sidebar-section-content">
              {dependenciesQuery.isPending && (
                <div className="calkit-sidebar-section-empty">Loading...</div>
              )}
              {!dependenciesQuery.isPending &&
                dependenciesList.length === 0 && (
                  <div className="calkit-sidebar-section-empty">All set!</div>
                )}
              {!dependenciesQuery.isPending && dependenciesList.length > 0 && (
                <div className="calkit-setup-list">
                  {dependenciesList.map((dep) => {
                    const status = (dep.status || "").toLowerCase();
                    const isOk =
                      status === "ok" ||
                      status === "ready" ||
                      status === "installed" ||
                      dep.installed === true;
                    const needsEnv = dep.env_var && !dep.value;
                    const missing =
                      dep.installed === false ||
                      dep.configured === false ||
                      Boolean(dep.missing_reason) ||
                      needsEnv;
                    const showWarning = missing || !isOk;
                    return (
                      <div
                        key={dep.name}
                        className={`calkit-setup-item${
                          showWarning ? " warning" : ""
                        }`}
                      >
                        <div className="calkit-setup-main">
                          <div className="calkit-setup-name">{dep.name}</div>
                          <div className="calkit-setup-kind">{dep.kind}</div>
                        </div>
                        <div className="calkit-setup-status">
                          {showWarning ? (
                            <span className="calkit-setup-chip warning">
                              Needs setup
                            </span>
                          ) : (
                            <span className="calkit-setup-chip ok">OK</span>
                          )}
                          {dep.version && (
                            <span className="calkit-setup-version">
                              {dep.version}
                            </span>
                          )}
                          {dep.missing_reason && (
                            <div className="calkit-setup-message">
                              {dep.missing_reason}
                            </div>
                          )}
                          {needsEnv && dep.env_var && (
                            <div className="calkit-setup-message">
                              Set {dep.env_var} in .env
                            </div>
                          )}
                        </div>
                        <div className="calkit-setup-actions">
                          {dep.installable && (
                            <button
                              className="calkit-setup-install"
                              disabled={installingDependency === dep.name}
                              onClick={() => handleInstallDependency(dep)}
                            >
                              {installingDependency === dep.name
                                ? "Installing..."
                                : "Install"}
                            </button>
                          )}
                          {dep.env_var && (
                            <button
                              className="calkit-setup-install"
                              onClick={() => {
                                navigator.clipboard?.writeText(
                                  dep.env_var || "",
                                );
                              }}
                            >
                              Copy env var
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
          {isExpanded && sectionId === "history" && (
            <div className="calkit-sidebar-section-content">
              <div className="calkit-git-history">
                {/* Modified files subsection */}
                {(gitStatus.changed?.length || 0) > 0 && (
                  <div className="calkit-git-subsection">
                    <div
                      className="calkit-git-subsection-header"
                      onClick={() => {
                        setExpandedGitSubsections((prev) => {
                          const next = new Set(prev);
                          if (next.has("modified")) {
                            next.delete("modified");
                          } else {
                            next.add("modified");
                          }
                          return next;
                        });
                      }}
                    >
                      <span className="calkit-git-subsection-icon">
                        {expandedGitSubsections.has("modified") ? "▼" : "▶"}
                      </span>
                      <span className="calkit-git-subsection-title">
                        Modified ({gitStatus.changed?.length || 0})
                      </span>
                    </div>
                    {expandedGitSubsections.has("modified") && (
                      <div className="calkit-git-subsection-items">
                        {gitStatus.changed?.slice(0, 10).map((path: string) => (
                          <div key={path} className="calkit-git-file-item">
                            {path}
                          </div>
                        ))}
                        {(gitStatus.changed?.length || 0) > 10 && (
                          <div className="calkit-git-file-more">
                            +{(gitStatus.changed?.length || 0) - 10} more
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Staged files subsection */}
                {(gitStatus.staged?.length || 0) > 0 && (
                  <div className="calkit-git-subsection">
                    <div
                      className="calkit-git-subsection-header"
                      onClick={() => {
                        setExpandedGitSubsections((prev) => {
                          const next = new Set(prev);
                          if (next.has("staged")) {
                            next.delete("staged");
                          } else {
                            next.add("staged");
                          }
                          return next;
                        });
                      }}
                    >
                      <span className="calkit-git-subsection-icon">
                        {expandedGitSubsections.has("staged") ? "▼" : "▶"}
                      </span>
                      <span className="calkit-git-subsection-title">
                        Staged ({gitStatus.staged?.length || 0})
                      </span>
                    </div>
                    {expandedGitSubsections.has("staged") && (
                      <div className="calkit-git-subsection-items">
                        {gitStatus.staged?.slice(0, 10).map((path: string) => (
                          <div key={path} className="calkit-git-file-item">
                            {path}
                          </div>
                        ))}
                        {(gitStatus.staged?.length || 0) > 10 && (
                          <div className="calkit-git-file-more">
                            +{(gitStatus.staged?.length || 0) - 10} more
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* Untracked files subsection */}
                {(gitStatus.untracked?.length || 0) > 0 && (
                  <div className="calkit-git-subsection">
                    <div
                      className="calkit-git-subsection-header"
                      onClick={() => {
                        setExpandedGitSubsections((prev) => {
                          const next = new Set(prev);
                          if (next.has("untracked")) {
                            next.delete("untracked");
                          } else {
                            next.add("untracked");
                          }
                          return next;
                        });
                      }}
                    >
                      <span className="calkit-git-subsection-icon">
                        {expandedGitSubsections.has("untracked") ? "▼" : "▶"}
                      </span>
                      <span className="calkit-git-subsection-title">
                        Untracked ({gitStatus.untracked?.length || 0})
                      </span>
                    </div>
                    {expandedGitSubsections.has("untracked") && (
                      <div className="calkit-git-subsection-items">
                        {gitStatus.untracked
                          ?.slice(0, 10)
                          .map((path: string) => (
                            <div key={path} className="calkit-git-file-item">
                              {path}
                            </div>
                          ))}
                        {(gitStatus.untracked?.length || 0) > 10 && (
                          <div className="calkit-git-file-more">
                            +{(gitStatus.untracked?.length || 0) - 10} more
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {/* No changes message */}
                {(gitStatus.changed?.length || 0) === 0 &&
                  (gitStatus.staged?.length || 0) === 0 &&
                  (gitStatus.untracked?.length || 0) === 0 && (
                    <div className="calkit-sidebar-section-empty">
                      No changes
                    </div>
                  )}

                {/* Recent history subsection */}
                <div className="calkit-git-subsection">
                  <div
                    className="calkit-git-subsection-header"
                    onClick={() => {
                      setExpandedGitSubsections((prev) => {
                        const next = new Set(prev);
                        if (next.has("history")) {
                          next.delete("history");
                        } else {
                          next.add("history");
                        }
                        return next;
                      });
                    }}
                  >
                    <span className="calkit-git-subsection-icon">
                      {expandedGitSubsections.has("history") ? "▼" : "▶"}
                    </span>
                    <span className="calkit-git-subsection-title">
                      Recent history
                    </span>
                  </div>
                  {expandedGitSubsections.has("history") && (
                    <div className="calkit-git-subsection-items">
                      {gitHistory.length === 0 && (
                        <div className="calkit-sidebar-section-empty">
                          No history
                        </div>
                      )}
                      {gitHistory.slice(0, 5).map((c: any) => (
                        <div key={c.hash} className="calkit-git-history-item">
                          <div className="calkit-git-history-message">
                            {c.message}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
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
                  : sectionId === "pipelineStages"
                  ? items.map((stage) => renderPipelineStage(stage))
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
      renderPipelineStage,
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
                      await showEnvironmentEditor({
                        mode: "edit",
                        initialName: env.id,
                        initialKind: env.kind || "unknown",
                        initialPath: env.path,
                        initialPackages: env.packages || [],
                        onSubmit: async ({ name, kind, path, packages }) => {
                          try {
                            await requestAPI("environments", {
                              method: "POST",
                              body: JSON.stringify({
                                name,
                                kind,
                                path,
                                packages,
                              }),
                            });
                          } catch (error) {
                            console.error(
                              "Failed to update environment:",
                              error,
                            );
                            throw error;
                          }
                        },
                      });
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
                      if (!confirm.button.accept) {
                        return;
                      }
                      try {
                        await deleteEnvironmentMutation.mutateAsync(env.id);
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
      {pipelineContextMenu?.visible &&
        ReactDOM.createPortal(
          <div
            className="calkit-env-context-menu"
            style={{ left: pipelineContextMenu.x, top: pipelineContextMenu.y }}
          >
            <div
              className="calkit-env-context-item"
              onClick={() => {
                setPipelineContextMenu(null);
                handleCreateStage();
              }}
            >
              New stage
            </div>
            <div
              className="calkit-env-context-item"
              onClick={() => {
                setPipelineContextMenu(null);
                handleRunPipeline();
              }}
            >
              Run pipeline
            </div>
          </div>,
          document.body,
        )}
      {stageContextMenu?.visible &&
        stageContextMenu.stage &&
        ReactDOM.createPortal(
          <div
            className="calkit-env-context-menu"
            style={{ left: stageContextMenu.x, top: stageContextMenu.y }}
          >
            <div
              className="calkit-env-context-item"
              onClick={() => {
                const s = stageContextMenu.stage!;
                setStageContextMenu(null);
                handleRunStage(s.id);
              }}
            >
              Run stage
            </div>
          </div>,
          document.body,
        )}
      {pipelineError &&
        ReactDOM.createPortal(
          <div
            className="calkit-modal-overlay"
            onClick={() => setPipelineError(null)}
          >
            <div
              className="calkit-modal-content"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="calkit-modal-header">
                <h2>Pipeline Error</h2>
                <button
                  className="calkit-modal-close"
                  onClick={() => setPipelineError(null)}
                >
                  ×
                </button>
              </div>
              <div className="calkit-modal-body">
                <div className="calkit-error-message">{pipelineError}</div>
              </div>
              <div className="calkit-modal-footer">
                <button
                  className="calkit-modal-button"
                  onClick={() => setPipelineError(null)}
                >
                  Close
                </button>
              </div>
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
  private _commands: CommandRegistry | null = null;
  private _hasAttention = false;
  private _expandPipelineSectionCallback: (() => void) | null = null;

  private _handleStatusChange = (needsAttention: boolean) => {
    if (this._hasAttention === needsAttention) {
      return;
    }
    this._hasAttention = needsAttention;
    const classes = new Set(
      `${this.title.className || ""} calkit-sidebar-tab`
        .split(/\s+/)
        .filter(Boolean),
    );
    if (needsAttention) {
      classes.add("calkit-sidebar-attention");
    } else {
      classes.delete("calkit-sidebar-attention");
    }
    this.title.className = Array.from(classes).join(" ");
    this.node.classList.toggle("calkit-sidebar-attention", needsAttention);
  };

  constructor() {
    super();
    this.addClass("calkit-sidebar-widget");
    this.title.className = "calkit-sidebar-tab";
  }

  setSettings(settings: ISettingRegistry.ISettings) {
    this._settings = settings;
    this.update();
  }

  setStateDB(stateDB: IStateDB) {
    this._stateDB = stateDB;
    this.update();
  }

  setCommands(commands: CommandRegistry) {
    this._commands = commands;
    this.update();
  }

  setExpandPipelineSectionCallback(callback: () => void) {
    this._expandPipelineSectionCallback = callback;
  }

  expandPipelineSection = () => {
    this._expandPipelineSectionCallback?.();
  };

  render() {
    return (
      <QueryClientProvider client={queryClient}>
        <CalkitSidebar
          settings={this._settings}
          stateDB={this._stateDB}
          onStatusChange={this._handleStatusChange}
          commands={this._commands || undefined}
          onSetExpandPipelineCallback={this.setExpandPipelineSectionCallback.bind(
            this,
          )}
        />
        {ReactDOM.createPortal(
          <ReactQueryDevtools initialIsOpen={false} />,
          document.body,
        )}
      </QueryClientProvider>
    );
  }
}
