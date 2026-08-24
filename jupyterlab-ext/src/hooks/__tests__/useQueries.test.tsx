import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import {
  useProject,
  useGitStatus,
  usePipelineStatus,
  useGitHistory,
  useNotebooks,
  useCreateNotebook,
  useCommit,
  usePush,
  useSetNotebookEnvironment,
  useSetNotebookStage,
} from "../useQueries";
import { requestAPI } from "../../request";
import { isFeatureEnabled } from "../../feature-flags";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { ReactNode } from "react";

jest.mock("../../request");

/**
 * Create a QueryClient provider wrapper for tests
 */
const createTestWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
};

describe("useQueries", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe("Query hooks", () => {
    it("useProject should fetch project data", async () => {
      const mockData = {
        name: "test-project",
        title: "Test Project",
        description: "A test project",
        git_repo_url: "https://github.com/test/test",
        owner: "test-owner",
        environments: {},
        notebooks: {},
        datasets: [],
        questions: [],
        models: {},
      };

      (requestAPI as jest.Mock).mockResolvedValue(mockData);

      const TestComponent = () => {
        const { data, isSuccess } = useProject();
        if (!isSuccess) return null;
        return <div>{data?.name}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("test-project")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("project");
    });

    (isFeatureEnabled("history") ? it : it.skip)(
      "useGitStatus should fetch git status",
      async () => {
        const mockStatus = {
          changed: ["file.txt"],
          staged: [],
          untracked: [],
          tracked: ["file.txt"],
          sizes: {},
          ahead: 0,
          behind: 0,
        };

        (requestAPI as jest.Mock).mockResolvedValue(mockStatus);

        const TestComponent = () => {
          const { data, isSuccess } = useGitStatus();
          if (!isSuccess) return null;
          return <div>{data?.changed.length}</div>;
        };

        render(<TestComponent />, { wrapper: createTestWrapper() });

        await waitFor(() => {
          expect(screen.getByText("1")).toBeInTheDocument();
        });

        expect(requestAPI).toHaveBeenCalledWith("git/status");
      },
    );

    it("usePipelineStatus should fetch pipeline status", async () => {
      const mockPipeline = {
        pipeline: {},
        is_outdated: false,
        stale_stages: {},
      };

      (requestAPI as jest.Mock).mockResolvedValue(mockPipeline);

      const TestComponent = () => {
        const { data, isSuccess } = usePipelineStatus();
        if (!isSuccess) return null;
        return <div>{data?.is_outdated ? "outdated" : "current"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("current")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("pipeline/status");
    });

    (isFeatureEnabled("history") ? it : it.skip)(
      "useGitHistory should fetch git history",
      async () => {
        const mockHistory = {
          commits: [
            {
              hash: "abc123",
              message: "Initial commit",
              author: "Test Author",
              date: "2024-01-01",
            },
          ],
        };

        (requestAPI as jest.Mock).mockResolvedValue(mockHistory);

        const TestComponent = () => {
          const { data, isSuccess } = useGitHistory();
          if (!isSuccess) return null;
          return <div>{data?.commits.length}</div>;
        };

        render(<TestComponent />, { wrapper: createTestWrapper() });

        await waitFor(() => {
          expect(screen.getByText("1")).toBeInTheDocument();
        });

        expect(requestAPI).toHaveBeenCalledWith("git/history");
      },
    );

    it("useNotebooks should fetch notebooks list", async () => {
      const mockNotebooks = [
        {
          path: "notebook1.ipynb",
          environment: null,
          stage: null,
          notebook: {},
        },
      ];

      (requestAPI as jest.Mock).mockResolvedValue(mockNotebooks);

      const TestComponent = () => {
        const { data, isSuccess } = useNotebooks();
        if (!isSuccess) return null;
        return <div>{data?.length}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("1")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("notebooks");
    });
  });

  describe("Mutation hooks", () => {
    it("useCreateNotebook should post notebook data", async () => {
      (requestAPI as jest.Mock).mockResolvedValue({ success: true });

      const TestComponent = () => {
        const { mutate, isSuccess } = useCreateNotebook();
        React.useEffect(() => {
          mutate({ name: "test.ipynb", path: "/path/to/test.ipynb" });
        }, [mutate]);
        return <div>{isSuccess ? "done" : "pending"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("done")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("notebooks", {
        method: "POST",
        body: JSON.stringify({
          name: "test.ipynb",
          path: "/path/to/test.ipynb",
        }),
      });
    });

    it("useCommit should post commit data", async () => {
      (requestAPI as jest.Mock).mockResolvedValue({ success: true });

      const TestComponent = () => {
        const { mutate, isSuccess } = useCommit();
        React.useEffect(() => {
          mutate({ message: "Test commit" });
        }, [mutate]);
        return <div>{isSuccess ? "done" : "pending"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("done")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("git/commit", {
        method: "POST",
        body: JSON.stringify({ message: "Test commit" }),
      });
    });

    it("usePush should call git push endpoint", async () => {
      (requestAPI as jest.Mock).mockResolvedValue({ success: true });

      const TestComponent = () => {
        const { mutate, isSuccess } = usePush();
        React.useEffect(() => {
          mutate();
        }, [mutate]);
        return <div>{isSuccess ? "done" : "pending"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("done")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("git/push", {
        method: "POST",
      });
    });

    it("useSetNotebookEnvironment should update notebook environment", async () => {
      (requestAPI as jest.Mock).mockResolvedValue({ success: true });

      const TestComponent = () => {
        const { mutate, isSuccess } = useSetNotebookEnvironment();
        React.useEffect(() => {
          mutate({ path: "test.ipynb", environment: "py39" });
        }, [mutate]);
        return <div>{isSuccess ? "done" : "pending"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("done")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("notebook/environment", {
        method: "PUT",
        body: JSON.stringify({ path: "test.ipynb", environment: "py39" }),
      });
    });

    it("useSetNotebookStage should update notebook stage", async () => {
      (requestAPI as jest.Mock).mockResolvedValue({ success: true });

      const TestComponent = () => {
        const { mutate, isSuccess } = useSetNotebookStage();
        React.useEffect(() => {
          mutate({
            path: "test.ipynb",
            stage_name: "process",
            environment: "py39",
            inputs: ["input.csv"],
            outputs: ["output.csv"],
          });
        }, [mutate]);
        return <div>{isSuccess ? "done" : "pending"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("done")).toBeInTheDocument();
      });

      expect(requestAPI).toHaveBeenCalledWith("notebook/stage", {
        method: "PUT",
        body: JSON.stringify({
          path: "test.ipynb",
          stage_name: "process",
          environment: "py39",
          inputs: ["input.csv"],
          outputs: ["output.csv"],
        }),
      });
    });
  });

  describe("Error handling", () => {
    it("useProject should handle errors", async () => {
      const error = new Error("API error");
      (requestAPI as jest.Mock).mockRejectedValue(error);

      const TestComponent = () => {
        const { isError } = useProject();
        return <div>{isError && "error"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("error")).toBeInTheDocument();
      });
    });

    it("useCommit should handle mutation errors", async () => {
      const error = new Error("Commit failed");
      (requestAPI as jest.Mock).mockRejectedValue(error);

      const TestComponent = () => {
        const { mutate, isError } = useCommit();
        React.useEffect(() => {
          mutate({ message: "Test" });
        }, [mutate]);
        return <div>{isError && "error"}</div>;
      };

      render(<TestComponent />, { wrapper: createTestWrapper() });

      await waitFor(() => {
        expect(screen.getByText("error")).toBeInTheDocument();
      });
    });
  });
});
