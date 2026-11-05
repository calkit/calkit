import { createFileRoute, redirect, useRouter } from "@tanstack/react-router"
import { z } from "zod"

import NewProjectModal from "../../components/Projects/NewProjectModal"
import { isLoggedIn } from "../../hooks/useAuth"

// Kept as a route so signup can redirect here and the landing page can link
// to a chosen source. Everywhere inside the app opens the modal in place
// instead, which leaves the page behind it on screen.
const searchSchema = z.object({
  path: z.enum(["existing", "fresh", "overleaf"]).optional().catch(undefined),
})

export const Route = createFileRoute("/_layout/new")({
  component: NewProjectRoute,
  validateSearch: (search) => searchSchema.parse(search),
  beforeLoad: () => {
    if (!isLoggedIn()) {
      localStorage.setItem("post_login_redirect", "/new")
      throw redirect({ to: "/login" })
    }
  },
})

function NewProjectRoute() {
  const router = useRouter()
  const { path } = Route.useSearch()
  // Back to whatever was open before, rather than always home. Arriving
  // straight from signup has nothing behind it, so that falls back home.
  const close = () => {
    if (router.history.canGoBack()) {
      router.history.back()
      return
    }
    router.navigate({ to: "/" })
  }
  return (
    <NewProjectModal
      isOpen
      onClose={close}
      initialPath={path}
      onCreated={(project) => {
        router.navigate({
          to: "/$accountName/$projectName",
          params: {
            accountName: project.owner_account_name,
            projectName: project.name,
          },
        })
      }}
    />
  )
}
