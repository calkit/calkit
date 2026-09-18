import { createFileRoute, redirect } from "@tanstack/react-router"

/**
 * Kept so existing links and bookmarks still work.
 *
 * Signing in and creating an account are one page now; the providers create
 * the account on first use either way.
 */
export const Route = createFileRoute("/signup")({
  beforeLoad: () => {
    throw redirect({ to: "/login", search: { create: true } })
  },
})
