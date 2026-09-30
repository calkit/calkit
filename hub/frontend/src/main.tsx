import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import ReactDOM from "react-dom/client"

import { StrictMode } from "react"
import { client } from "./client/client.gen"
import NotFound from "./components/Common/NotFound"
import { initAnalytics, sensitivePropertyBlacklist } from "./lib/analytics"
import { getValidAccessToken } from "./lib/auth"
import { reloadOnStaleChunk } from "./lib/staleChunks"
import { routeTree } from "./routeTree.gen"
import theme from "./theme"

reloadOnStaleChunk(window)

client.setConfig({ baseURL: import.meta.env.VITE_API_URL })
// The token resolver needs the request URL to avoid refreshing recursively
// when requesting the refresh endpoint itself, so attach it with an axios
// interceptor rather than the client's auth callback.
client.instance.interceptors.request.use(async (config) => {
  const token = await getValidAccessToken(config.url)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

const mixpanelToken = import.meta.env.VITE_MIXPANEL_TOKEN
mixpanel.init(mixpanelToken, {
  debug: String(import.meta.env.VITE_API_URL).startsWith(
    "http://api.localhost",
  ),
  // Page views are tracked in lib/analytics instead of automatically here, so
  // automated sessions can be tagged before any event is sent.
  track_pageview: false,
  persistence: "localStorage",
  // Mixpanel is initialized opted out, so it sends and stores nothing until
  // the visitor accepts analytics in the consent banner. Anonymous page views
  // are counted by the hub separately, without this SDK (see lib/analytics).
  opt_out_tracking_by_default: true,
  opt_out_persistence_by_default: true,
  // Our URLs can carry secrets, e.g., reset and invitation tokens, so Mixpanel
  // never receives the full current URL or referrer
  property_blacklist: sensitivePropertyBlacklist,
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
