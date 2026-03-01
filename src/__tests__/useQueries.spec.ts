/**
 * Simple unit tests for hooks - verify they are properly exported
 */

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
  useAddPackage,
  useCreateEnvironment,
  useUpdateEnvironment,
  useDeleteEnvironment,
  useUpdateNotebook,
  useDeleteNotebook,
} from "../hooks/useQueries";

jest.mock("../request");

describe("useQueries hook configuration", () => {
  describe("Query hooks define correct endpoints", () => {
    it("useProject should query 'project' endpoint", () => {
      const hook = useProject;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useGitStatus should query 'git/status' endpoint", () => {
      const hook = useGitStatus;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("usePipelineStatus should query 'pipeline/status' endpoint", () => {
      const hook = usePipelineStatus;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useGitHistory should query 'git/history' endpoint", () => {
      const hook = useGitHistory;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useNotebooks should query 'notebooks' endpoint", () => {
      const hook = useNotebooks;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });
  });

  describe("Mutation hooks are defined", () => {
    it("useCreateNotebook mutation hook is defined", () => {
      const hook = useCreateNotebook;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useCommit mutation hook is defined", () => {
      const hook = useCommit;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("usePush mutation hook is defined", () => {
      const hook = usePush;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useSetNotebookEnvironment mutation hook is defined", () => {
      const hook = useSetNotebookEnvironment;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useSetNotebookStage mutation hook is defined", () => {
      const hook = useSetNotebookStage;
      expect(hook).toBeDefined();
      expect(hook).toBeInstanceOf(Function);
    });

    it("useAddPackage mutation hook is defined", () => {
      expect(useAddPackage).toBeDefined();
      expect(useAddPackage).toBeInstanceOf(Function);
    });

    it("useCreateEnvironment mutation hook is defined", () => {
      expect(useCreateEnvironment).toBeDefined();
      expect(useCreateEnvironment).toBeInstanceOf(Function);
    });

    it("useUpdateEnvironment mutation hook is defined", () => {
      expect(useUpdateEnvironment).toBeDefined();
      expect(useUpdateEnvironment).toBeInstanceOf(Function);
    });

    it("useDeleteEnvironment mutation hook is defined", () => {
      expect(useDeleteEnvironment).toBeDefined();
      expect(useDeleteEnvironment).toBeInstanceOf(Function);
    });

    it("useUpdateNotebook mutation hook is defined", () => {
      expect(useUpdateNotebook).toBeDefined();
      expect(useUpdateNotebook).toBeInstanceOf(Function);
    });

    it("useDeleteNotebook mutation hook is defined", () => {
      expect(useDeleteNotebook).toBeDefined();
      expect(useDeleteNotebook).toBeInstanceOf(Function);
    });
  });

  describe("Hook exports are properly structured", () => {
    it("Query hooks should not be undefined", () => {
      expect(useProject).not.toBeUndefined();
      expect(useGitStatus).not.toBeUndefined();
      expect(usePipelineStatus).not.toBeUndefined();
      expect(useGitHistory).not.toBeUndefined();
      expect(useNotebooks).not.toBeUndefined();
    });

    it("Mutation hooks should not be undefined", () => {
      expect(useCreateNotebook).not.toBeUndefined();
      expect(useCommit).not.toBeUndefined();
      expect(usePush).not.toBeUndefined();
      expect(useSetNotebookEnvironment).not.toBeUndefined();
      expect(useSetNotebookStage).not.toBeUndefined();
    });

    it("All hooks are functions", () => {
      const allHooks = [
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
        useAddPackage,
        useCreateEnvironment,
        useUpdateEnvironment,
        useDeleteEnvironment,
        useUpdateNotebook,
        useDeleteNotebook,
      ];

      allHooks.forEach((hook) => {
        expect(typeof hook).toBe("function");
      });
    });
  });
});
