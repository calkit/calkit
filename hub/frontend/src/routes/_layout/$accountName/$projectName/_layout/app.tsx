import { createFileRoute, redirect } from "@tanstack/react-router"

// Projects can have more than one app, so this page moved to /apps. Kept as
// a redirect since the old path is linked from elsewhere and bookmarked.
export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/app",
)({
  beforeLoad: ({ params, search }) => {
    throw redirect({
      to: "/$accountName/$projectName/apps",
      params,
      search,
    })
  },
})
