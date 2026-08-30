import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef } from "react"

import { type Figure, type Issue, ProjectsService } from "../client"
import { dataOrNull, httpStatus } from "../lib/api"
import { isAuthenticationError } from "../lib/auth"

const useProject = (accountName: string, projectName: string, ref?: string) => {
  const queryClient = useQueryClient()

  const projectRequest = useQuery({
    queryKey: ["projects", accountName, projectName],
    queryFn: () =>
      ProjectsService.getProject({
        owner_name: accountName,
        project_name: projectName,
        get_extended_info: true,
      }).then((response) => response.data),
    retry: (failureCount, error) => {
      // A session/token error clears once the token layer refreshes (see the
      // rotation grace window server-side), so retry it a couple of times
      // rather than surfacing it as a missing project. Genuine not-found or
      // permission denials shouldn't retry.
      if (isAuthenticationError(error)) {
        return failureCount < 2
      }
      const status = (error as any)?.response?.status ?? (error as any)?.status
      if (status === 404 || status === 403) {
        return false
      }
      return failureCount < 3
    },
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  const userHasWriteAccess = ["owner", "admin", "write"].includes(
    String(projectRequest.data?.current_user_access),
  )
  // Managing collaborators and invite links requires admin (or owner).
  const userHasAdminAccess = ["owner", "admin"].includes(
    String(projectRequest.data?.current_user_access),
  )

  const showcaseRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "showcase", ref],
    queryFn: () =>
      ProjectsService.getProjectShowcase({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then(dataOrNull),
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  const putDevcontainerMutation = useMutation({
    mutationFn: () =>
      ProjectsService.putProjectDevContainer({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "repro-check"],
      }),
  })

  return {
    projectRequest,
    userHasWriteAccess,
    userHasAdminAccess,
    showcaseRequest,
    putDevcontainerMutation,
  }
}

const useProjectReadme = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const readmeRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "readme", ref],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
        path: "README.md",
        ref,
      }).then((response) => response.data),
    // A project with no README 404s, and that's an answer, not a failure.
    // The default three retries turned one miss into four requests against
    // an endpoint that resolves the project's whole DVC index, and the
    // backoff between them (1s, 2s, 4s) kept the README panel spinning for
    // seconds after the first reply had already settled the question.
    retry: (failureCount, error) =>
      httpStatus(error) !== 404 && failureCount < 3,
  })
  return { readmeRequest }
}

const useProjectQuestions = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const questionsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "questions", ref],
    queryFn: () =>
      ProjectsService.getProjectQuestions({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  return { questionsRequest }
}

const FIGURES_PAGE_LIMIT = 100

// The figures endpoint is paginated because it inlines each figure's content.
// Callers here want the complete list to populate a picker, and only need
// paths and titles for it, so they ask for metadata only (no object-storage
// reads at all) and page through to the end rather than silently stopping at
// whatever the first page happened to hold.
const useProjectFigures = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const figuresRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "figures", ref, "all"],
    queryFn: async () => {
      const all: Figure[] = []
      for (;;) {
        const page = await ProjectsService.getProjectFigures({
          owner_name: accountName,
          project_name: projectName,
          ref,
          limit: FIGURES_PAGE_LIMIT,
          offset: all.length,
          include_content: false,
        }).then((response) => response.data)
        if (!page?.items?.length) break
        all.push(...page.items)
        if (all.length >= page.total) break
      }
      return all
    },
  })
  return { figuresRequest }
}

const useProjectResults = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const resultsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "results", ref],
    queryFn: () =>
      ProjectsService.getProjectResults({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  return { resultsRequest }
}

const useProjectFiles = (accountName: string, projectName: string) => {
  const filesRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "files"],
    queryFn: () =>
      ProjectsService.getProjectContents({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
  })
  return { filesRequest }
}

const useProjectDatasets = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const datasetsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "datasets", ref],
    queryFn: () =>
      ProjectsService.getProjectDatasets({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })

  return { datasetsRequest }
}

const useProjectEnvironments = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const environmentsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "environments", ref],
    queryFn: () =>
      ProjectsService.getProjectEnvironments({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })

  return { environmentsRequest }
}

const useProjectPublications = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const publicationsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "publications", ref],
    queryFn: () =>
      ProjectsService.getProjectPublications({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  return { publicationsRequest }
}

const useProjectPresentations = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const presentationsRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "presentations", ref],
    queryFn: () =>
      ProjectsService.getProjectPresentations({
        owner_name: accountName,
        project_name: projectName,
        ref,
      }).then((response) => response.data),
  })
  return { presentationsRequest }
}

const useProjectTables = (
  accountName: string,
  projectName: string,
  ref?: string,
  includeContent = true,
) => {
  const tablesRequest = useQuery({
    queryKey: [
      "projects",
      accountName,
      projectName,
      "tables",
      ref,
      includeContent,
    ],
    queryFn: () =>
      ProjectsService.getProjectTables({
        owner_name: accountName,
        project_name: projectName,
        ref,
        include_content: includeContent,
      }).then((response) => response.data),
  })
  return { tablesRequest }
}

const useProjectIssues = (accountName: string, projectName: string) => {
  const queryClient = useQueryClient()

  const issuesKey = ["projects", accountName, projectName, "issues"] as const

  // GitHub's REST list endpoint is eventually consistent, so a plain refetch
  // shortly after a write can return a stale list and clobber the optimistic
  // change. Instead of invalidating, we refetch and *merge*: optimistic
  // changes the server hasn't caught up to yet are re-applied, and we keep
  // re-checking (with a cap) until the server confirms them.
  const ISSUES_RECONCILE_DELAY_MS = 5000
  const ISSUES_RECONCILE_MAX_ATTEMPTS = 6
  // issueNumber -> the state we expect the server to eventually report.
  const pendingStates = useRef(new Map<number, Issue["state"]>())
  // issueNumber -> a created issue the server list may not include yet.
  const pendingCreates = useRef(new Map<number, Issue>())
  const reconcileTimer = useRef<ReturnType<typeof setTimeout>>()
  const reconcileAttempts = useRef(0)

  const hasPending = () =>
    pendingStates.current.size > 0 || pendingCreates.current.size > 0

  // Overlay still-unconfirmed optimistic changes onto a list of issues.
  const applyPending = (list: Issue[]): Issue[] => {
    let result = list.map((i) => {
      const want = pendingStates.current.get(i.number)
      return want && i.state !== want ? { ...i, state: want } : i
    })
    const present = new Set(result.map((i) => i.number))
    for (const [num, issue] of pendingCreates.current) {
      if (!present.has(num)) result = [issue, ...result]
    }
    return result
  }

  const reconcileIssues = async () => {
    let server: Issue[]
    try {
      server = await ProjectsService.getProjectIssues({
        owner_name: accountName,
        project_name: projectName,
        state: "all",
      }).then((response) => response.data)
    } catch {
      return // Leave the optimistic cache as-is; try again later.
    }
    const serverByNum = new Map(server.map((i) => [i.number, i]))
    // Drop expectations the server now satisfies.
    for (const [num, want] of [...pendingStates.current]) {
      if (serverByNum.get(num)?.state === want) {
        pendingStates.current.delete(num)
      }
    }
    for (const num of [...pendingCreates.current.keys()]) {
      if (serverByNum.has(num)) pendingCreates.current.delete(num)
    }
    queryClient.setQueryData<Issue[]>(issuesKey, applyPending(server))
    // Keep reconciling until the server agrees, up to a cap (after which we
    // accept the server's truth, e.g. a change reverted elsewhere).
    if (
      hasPending() &&
      reconcileAttempts.current < ISSUES_RECONCILE_MAX_ATTEMPTS
    ) {
      reconcileAttempts.current += 1
      scheduleIssuesReconcile(false)
    } else {
      pendingStates.current.clear()
      pendingCreates.current.clear()
    }
  }

  // `fresh` resets the attempt counter — a new user action restarts the
  // window the server is given to catch up.
  const scheduleIssuesReconcile = (fresh = true) => {
    if (fresh) reconcileAttempts.current = 0
    if (reconcileTimer.current) clearTimeout(reconcileTimer.current)
    reconcileTimer.current = setTimeout(
      reconcileIssues,
      ISSUES_RECONCILE_DELAY_MS,
    )
  }

  // Always fetch every issue and let the UI filter open vs. closed. A single
  // cache keeps the list consistent no matter how the "show closed" toggle is
  // flipped, and lets optimistic updates apply in one place.
  const issuesRequest = useQuery({
    queryKey: issuesKey,
    queryFn: () =>
      ProjectsService.getProjectIssues({
        owner_name: accountName,
        project_name: projectName,
        state: "all",
      }).then((response) => response.data),
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  interface IssueStateChange {
    state: "open" | "closed"
    issueNumber: number
  }

  const issueStateMutation = useMutation({
    mutationFn: (data: IssueStateChange) =>
      ProjectsService.patchProjectIssue({
        owner_name: accountName,
        project_name: projectName,
        issue_number: data.issueNumber,
        issuePatch: { state: data.state },
      }).then((response) => response.data),
    // Optimistically flip the issue's state so the UI updates instantly
    // despite GitHub's eventual consistency.
    onMutate: async (data: IssueStateChange) => {
      await queryClient.cancelQueries({ queryKey: issuesKey })
      const prevState = queryClient
        .getQueryData<Issue[]>(issuesKey)
        ?.find((i) => i.number === data.issueNumber)?.state
      pendingStates.current.set(data.issueNumber, data.state)
      queryClient.setQueryData<Issue[]>(issuesKey, (old) =>
        old?.map((i) =>
          i.number === data.issueNumber ? { ...i, state: data.state } : i,
        ),
      )
      return { prevState }
    },
    // Roll back only the mutated issue so we don't clobber other cache
    // writes (e.g. a newly created issue) that happened in the meantime.
    onError: (_err, data, context) => {
      pendingStates.current.delete(data.issueNumber)
      if (context?.prevState !== undefined) {
        queryClient.setQueryData<Issue[]>(issuesKey, (old) =>
          old?.map((i) =>
            i.number === data.issueNumber
              ? { ...i, state: context.prevState as Issue["state"] }
              : i,
          ),
        )
      }
    },
    onSettled: () => scheduleIssuesReconcile(),
  })

  // Called by the create-issue flow so the new issue is preserved through
  // reconciles until GitHub's list endpoint returns it.
  const registerCreatedIssue = (issue: Issue) => {
    pendingCreates.current.set(issue.number, issue)
    queryClient.setQueryData<Issue[]>(issuesKey, (old) =>
      old !== undefined ? [issue, ...old] : [issue],
    )
    scheduleIssuesReconcile()
  }

  return { issueStateMutation, issuesRequest, registerCreatedIssue }
}

export {
  useProjectFiles,
  useProjectFigures,
  useProjectResults,
  useProjectPublications,
  useProjectPresentations,
  useProjectTables,
  useProjectReadme,
  useProjectDatasets,
  useProjectEnvironments,
  useProjectIssues,
  useProjectQuestions,
}
export default useProject
