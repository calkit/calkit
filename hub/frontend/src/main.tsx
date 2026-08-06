import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import ReactDOM from "react-dom/client"
import mixpanel from "mixpanel-browser"

import { routeTree } from "./routeTree.gen"
import { StrictMode } from "react"
import { OpenAPI } from "./client"
import theme from "./theme"
import NotFound from "./components/Common/NotFound"
import { getValidAccessToken } from "./lib/auth"
import { initAnalytics } from "./lib/analytics"

OpenAPI.BASE = import.meta.env.VITE_API_URL
OpenAPI.TOKEN = async (options) => {
  return (await getValidAccessToken(options.url)) ?? ""
}

const mixpanelToken = import.meta.env.VITE_MIXPANEL_TOKEN
mixpanel.init(mixpanelToken, {
  debug: String(import.meta.env.VITE_API_URL).startsWith(
    "http://api.localhost",
  ),
  // Page views are tracked in lib/analytics instead of automatically here, so
  // automated sessions can be tagged before any event is sent.
  track_pageview: false,
  persistence: "localStorage",
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { refetchOnWindowFocus: false, refetchOnMount: true },
  },
})

const router = createRouter({
  routeTree,
  defaultNotFoundComponent: () => <NotFound />,
})
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router
  }
}
initAnalytics(router)

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ChakraProvider theme={theme}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </ChakraProvider>
  </StrictMode>,
)
