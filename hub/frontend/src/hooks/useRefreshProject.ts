import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"

import { ProjectsService } from "../client"
import { handleError } from "../lib/errors"
import useCustomToast from "./useCustomToast"

/**
 * Fetch the latest from the project's Git repo, then refetch everything
 * cached for the project, e.g., to pick up a branch pushed from elsewhere.
 */
const useRefreshProject = (accountName: string, projectName: string) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  return useMutation({
    mutationFn: () =>
      ProjectsService.postProjectSync({
        owner_name: accountName,
        project_name: projectName,
      }),
    onSuccess: () => {
      showToast("Refreshed", "Fetched the latest from the repo.", "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName],
      }),
  })
}

export default useRefreshProject
