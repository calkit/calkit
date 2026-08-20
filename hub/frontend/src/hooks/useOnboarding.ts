import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import axios from "axios"

import { type OnboardingFlags, UsersService } from "../client"
import { isLoggedIn } from "./useAuth"

const FLAGS_KEY = ["user", "onboarding-flags"]

/**
 * The onboarding steps this user has dismissed or marked done.
 *
 * One request covers every checklist on the page: the account-level one and
 * whichever project is open. Setting a flag writes through the cache before
 * the request lands, since a checklist item that stays unchecked for a round
 * trip reads as a click that didn't register.
 */
const useOnboardingFlags = (projectId?: string | null) => {
  const queryClient = useQueryClient()
  const flagsQuery = useQuery({
    queryKey: FLAGS_KEY,
    queryFn: () =>
      UsersService.getUserOnboardingFlags().then((response) => response.data),
    enabled: isLoggedIn(),
    staleTime: 60_000,
  })
  const accountFlags = flagsQuery.data?.account ?? []
  const projectFlags = projectId
    ? flagsQuery.data?.projects?.[projectId] ?? []
    : []
  const applyLocally = (step: string, add: boolean) => {
    queryClient.setQueryData<OnboardingFlags>(FLAGS_KEY, (old) => {
      const account = [...(old?.account ?? [])]
      const projects: Record<string, string[]> = { ...(old?.projects ?? {}) }
      const steps = projectId ? [...(projects[projectId] ?? [])] : account
      const updated = add
        ? steps.includes(step)
          ? steps
          : [...steps, step]
        : steps.filter((s) => s !== step)
      if (projectId) {
        projects[projectId] = updated
        return { account, projects }
      }
      return { account: updated, projects }
    })
  }
  const setFlagMutation = useMutation({
    mutationFn: ({ step, done }: { step: string; done: boolean }) =>
      done
        ? UsersService.postUserOnboardingFlag({
            onboardingFlagPost: { step, project_id: projectId ?? null },
          }).then((response) => response.data)
        : UsersService.deleteUserOnboardingFlag({
            step,
            project_id: projectId ?? null,
          }).then((response) => response.data),
    onMutate: ({ step, done }) => applyLocally(step, done),
    onSettled: () => queryClient.invalidateQueries({ queryKey: FLAGS_KEY }),
  })
  const setFlag = (step: string, done: boolean) =>
    setFlagMutation.mutate({ step, done })
  // Clears every flag the user has, on every project -- what "reset my
  // checklists" means from account settings, where no one project is in view.
  const resetAllMutation = useMutation({
    mutationFn: () =>
      UsersService.deleteAllUserOnboardingFlags().then(
        (response) => response.data,
      ),
    onSuccess: () =>
      queryClient.setQueryData<OnboardingFlags>(FLAGS_KEY, {
        account: [],
        projects: {},
      }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: FLAGS_KEY }),
  })
  const flagCount =
    (flagsQuery.data?.account?.length ?? 0) +
    Object.values(flagsQuery.data?.projects ?? {}).reduce(
      (total, steps) => total + steps.length,
      0,
    )
  return {
    flagsQuery,
    accountFlags,
    projectFlags,
    setFlag,
    resetAllMutation,
    flagCount,
  }
}

/**
 * Whether the local Calkit server is up, and whether it knows a project.
 *
 * The server usually isn't running, so both queries fail fast rather than
 * leaving a dropped connection to hang: a checklist that waits on localhost
 * would leave the whole card spinning for the majority of users who don't
 * have it up.
 */
export const useLocalServer = (accountName?: string, projectName?: string) => {
  const healthQuery = useQuery({
    queryKey: ["local-server-main"],
    queryFn: () => axios.get("http://localhost:8866/health", { timeout: 2000 }),
    retry: false,
  })
  const projectQuery = useQuery({
    queryKey: ["local-server-sidebar", accountName, projectName],
    queryFn: () =>
      axios.get(
        `http://localhost:8866/projects/${accountName}/${projectName}`,
        { timeout: 2000 },
      ),
    retry: false,
    enabled: Boolean(accountName && projectName),
  })
  return {
    cliRunning: healthQuery.data?.data === "All good!",
    projectConnected: Boolean(projectQuery.data?.data),
  }
}

export default useOnboardingFlags
