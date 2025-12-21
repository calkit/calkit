import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { requestAPI } from "../request";

/**
 * Type definitions for API responses
 */
export interface IProjectInfo {
  name: string;
  title: string;
  description: string;
  git_repo_url: string;
  owner: string;
  environments: Record<string, any>;
  pipeline?: { stages: Record<string, any> };
  notebooks: Record<string, any>;
  datasets: any[];
  questions: any[];
  models: Record<string, any>;
}

export interface IGitStatus {
  changed: string[];
  staged: string[];
  untracked: string[];
  tracked: string[];
  sizes: Record<string, number>;
  ahead: number;
  behind: number;
  branch?: string | null;
  remote?: string | null;
}

export interface IGitCommit {
  hash: string;
  message: string;
  author: string;
  date: string;
}

export interface IGitHistory {
  commits: IGitCommit[];
}

/**
 * Query hook for fetching project data (environments, notebooks, pipeline, etc.)
 */
export const useProject = () => {
  return useQuery<IProjectInfo>({
    queryKey: ["project"],
    queryFn: () => requestAPI<IProjectInfo>("project"),
  });
};

/**
 * Query hook for fetching git status
 */
export const useGitStatus = () => {
  return useQuery<IGitStatus>({
    queryKey: ["git", "status"],
    queryFn: () => requestAPI<IGitStatus>("git/status"),
    staleTime: 10 * 1000, // 10 seconds for git status
  });
};

/**
 * Query hook for fetching git history
 */
export const useGitHistory = () => {
  return useQuery<IGitHistory>({
    queryKey: ["git", "history"],
    queryFn: () => requestAPI<IGitHistory>("git/history"),
  });
};

/**
 * Mutation hook for creating a notebook
 * Automatically invalidates and refetches project data on success
 */
export const useCreateNotebook = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("notebook/create", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      // Invalidate project query to refetch notebooks, environments, and pipeline
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for registering a notebook
 * Automatically invalidates and refetches project data on success
 */
export const useRegisterNotebook = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("notebook/register", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      // Invalidate project query to refetch notebooks
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for adding a package to an environment
 * Automatically invalidates and refetches project data on success
 */
export const useAddPackage = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: { environment: string; package: string }) =>
      requestAPI("environment/add-package", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      // Invalidate project query to refetch environments
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for creating an environment
 * Automatically invalidates and refetches project data on success
 */
export const useCreateEnvironment = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("environment/create", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      // Invalidate project query to refetch environments and pipeline
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for committing changes
 * Automatically invalidates and refetches git status/history on success
 */
export const useCommit = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("git/commit", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      // Invalidate git queries to refetch status and history
      void queryClient.invalidateQueries({ queryKey: ["git"] });
    },
  });
};

/**
 * Mutation hook for pushing commits
 * Automatically invalidates and refetches git status on success
 */
export const usePush = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => requestAPI("git/push", { method: "POST" }),
    onSuccess: () => {
      // Invalidate git status query
      void queryClient.invalidateQueries({ queryKey: ["git", "status"] });
    },
  });
};

/**
 * Mutation hook for updating an environment
 */
export const useUpdateEnvironment = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("environment/update", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for deleting an environment
 */
export const useDeleteEnvironment = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (envName: string) =>
      requestAPI("environment/delete", {
        method: "POST",
        body: JSON.stringify({ name: envName }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for updating a notebook
 */
export const useUpdateNotebook = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: any) =>
      requestAPI("notebook/update", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};

/**
 * Mutation hook for deleting a notebook
 */
export const useDeleteNotebook = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notebookName: string) =>
      requestAPI("notebook/delete", {
        method: "POST",
        body: JSON.stringify({ name: notebookName }),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["project"] });
    },
  });
};
