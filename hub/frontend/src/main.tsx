import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider, createRouter } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import ReactDOM from "react-dom/client"

import { StrictMode } from "react"
import { client } from "./client/client.gen"
import NotFound from "./components/Common/NotFound"
import { initAnalytics } from "./lib/analytics"
import { getValidAccessToken } from "./lib/auth"
import { routeTree } from "./routeTree.gen"
import theme from "./theme"

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
