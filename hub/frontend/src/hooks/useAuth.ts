import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import { useState } from "react"
import mixpanel from "mixpanel-browser"

import { AxiosError } from "axios"
import {
  type Body_login_login_access_token as AccessToken,
  type ApiError,
  LoginService,
  type UserPublic,
  type UserRegister,
  UsersService,
} from "../client"
import useCustomToast from "./useCustomToast"
import {
  clearTokens,
  forceRefreshAccessToken,
  getAccessToken,
  popPostLoginRedirect,
  isAuthenticationError,
  storeTokens,
} from "../lib/auth"

const isLoggedIn = () => {
  return getAccessToken() !== null
}

const useAuth = () => {
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const {
    data: user,
    isLoading,
    error: getUserError,
  } = useQuery<UserPublic | null, Error>({
    queryKey: ["currentUser"],
    // On a token error, force one fresh refresh and retry before concluding the
    // session is dead. This recovers from an expired token that slipped through
    // (clock skew, a refresh/rotation race) instead of logging the user out.
    queryFn: async () => {
      try {
        return await UsersService.getCurrentUser()
      } catch (error) {
        if (isAuthenticationError(error)) {
          const token = await forceRefreshAccessToken()
          if (token) {
            return await UsersService.getCurrentUser()
          }
        }
        throw error
      }
    },
    enabled: isLoggedIn(),
    staleTime: Infinity,
    retry: (failureCount, error: any) => {
      const status = error?.status ?? error?.response?.status
      if (status >= 400 && status < 500) return false
      return failureCount < 3
    },
  })

  const signUpMutation = useMutation({
    mutationFn: (data: UserRegister) =>
      UsersService.registerUser({ requestBody: data }),
    onSuccess: () => {
      navigate({ to: "/login" })
      showToast(
        "Account created.",
        "Your account has been created successfully.",
        "success",
      )
    },
    onError: (err: ApiError) => {
      let errDetail = (err.body as any)?.detail
      if (err instanceof AxiosError) {
        errDetail = err.message
      }
      showToast("Something went wrong.", errDetail, "error")
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })

  const login = async (data: AccessToken) => {
    const response = await LoginService.accessToken({
      formData: data,
    })
    storeTokens(response.access_token, response.refresh_token)
  }

  const loginMutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      const redirectTo = popPostLoginRedirect()
      navigate({ to: redirectTo || "/" })
    },
    onError: (err: ApiError) => {
      let errDetail = (err.body as any)?.detail
      if (err instanceof AxiosError) {
        errDetail = err.message
      }
      if (Array.isArray(errDetail)) {
        errDetail = "Something went wrong"
      }
      setError(errDetail)
    },
  })

  const loginGithub = async (data: { code: string; redirectUri: string }) => {
    const response = await LoginService.withGithub({
      requestBody: {
        code: data.code,
        redirect_uri: data.redirectUri,
      },
    })
    storeTokens(response.access_token, response.refresh_token)
  }

  const loginGitHubMutation = useMutation({
    mutationFn: loginGithub,
    onSuccess: () => {
      const redirectTo = popPostLoginRedirect()
      navigate({ to: redirectTo || "/" })
    },
    onError: (err: ApiError) => {
      let errDetail = (err.body as any)?.detail
      if (err instanceof AxiosError) {
        errDetail = err.message
      }
      if (Array.isArray(errDetail)) {
        errDetail = "Something went wrong"
      }
      showToast("Something went wrong.", errDetail, "error")
      setError(errDetail)
    },
  })

  const loginGoogle = async (data: { code: string; redirectUri: string }) => {
    const response = await LoginService.withGoogle({
      requestBody: {
        code: data.code,
        redirect_uri: data.redirectUri,
      },
    })
    storeTokens(response.access_token, response.refresh_token)
  }

  const loginGoogleMutation = useMutation({
    mutationFn: loginGoogle,
    onSuccess: () => {
      const redirectTo = popPostLoginRedirect()
      navigate({ to: redirectTo || "/" })
    },
    onError: (err: ApiError) => {
      let errDetail = (err.body as any)?.detail
      if (err instanceof AxiosError) {
        errDetail = err.message
      }
      if (Array.isArray(errDetail)) {
        errDetail = "Something went wrong"
      }
      showToast("Something went wrong.", errDetail, "error")
      setError(errDetail)
    },
  })

  const logout = () => {
    clearTokens()
    mixpanel.reset()
    localStorage.removeItem("post_login_redirect")
    if (typeof window !== "undefined") {
      window.location.replace("/")
    } else {
      navigate({ to: "/" })
    }
  }

  if (getUserError && isLoggedIn()) {
    if (isAuthenticationError(getUserError)) {
      // Capture the trigger durably: logout() navigates away and wipes the
      // console, so persist to localStorage (read it back after a logout) and
      // send it to Mixpanel so we can see these across users.
      const err = getUserError as any
      const info = {
        status: err?.status ?? err?.response?.status,
        detail: err?.body?.detail ?? err?.response?.data?.detail,
        at: new Date().toISOString(),
      }
      console.warn("Session invalid, logging out", info)
      try {
        localStorage.setItem("last_auto_logout", JSON.stringify(info))
      } catch {}
      mixpanel.track("Session auto-logout", info)
      logout()
    }
  }

  return {
    signUpMutation,
    loginMutation,
    loginGitHubMutation,
    loginGoogleMutation,
    logout,
    user,
    isLoading,
    error,
    resetError: () => setError(null),
  }
}

export { isLoggedIn }
export default useAuth
