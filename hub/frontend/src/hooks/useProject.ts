import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useRef } from "react"

import { type Issue, ProjectsService } from "../client"
import { isAuthenticationError } from "../lib/auth"

const useProject = (accountName: string, projectName: string, ref?: string) => {
  const queryClient = useQueryClient()

  const projectRequest = useQuery({
    queryKey: ["projects", accountName, projectName],
    queryFn: () =>
      ProjectsService.getProject({
        ownerName: accountName,
        projectName: projectName,
        getExtendedInfo: true,
      }),
    retry: (failureCount, error) => {
      // A session/token error clears once the token layer refreshes (see the
      // rotation grace window server-side), so retry it a couple of times
      // rather than surfacing it as a missing project. Genuine not-found or
      // permission denials shouldn't retry.
      if (isAuthenticationError(error)) {
        return failureCount < 2
      }
      if (error.message === "Not Found" || error.message === "Forbidden") {
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
    refetchOnWindowFocus: false,
    refetchOnMount: false,
  })

  const putDevcontainerMutation = useMutation({
    mutationFn: () =>
      ProjectsService.putProjectDevContainer({
        ownerName: accountName,
        projectName: projectName,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        path: "README.md",
        ref,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })
  return { questionsRequest }
}

const useProjectFigures = (
  accountName: string,
  projectName: string,
  ref?: string,
) => {
  const figuresRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "figures", ref],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })
  return { resultsRequest }
}

const useProjectFiles = (accountName: string, projectName: string) => {
  const filesRequest = useQuery({
    queryKey: ["projects", accountName, projectName, "files"],
    queryFn: () =>
      ProjectsService.getProjectContents({
        ownerName: accountName,
        projectName: projectName,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
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
        ownerName: accountName,
        projectName: projectName,
        ref,
      }),
  })
  return { presentationsRequest }
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
        ownerName: accountName,
        projectName: projectName,
        state: "all",
      })
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
        ownerName: accountName,
        projectName: projectName,
        state: "all",
      }),
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
        ownerName: accountName,
        projectName: projectName,
        issueNumber: data.issueNumber,
        requestBody: { state: data.state },
      }),
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
  useProjectReadme,
  useProjectDatasets,
  useProjectEnvironments,
  useProjectIssues,
  useProjectQuestions,
}
export default useProject
