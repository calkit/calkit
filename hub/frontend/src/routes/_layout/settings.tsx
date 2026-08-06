import {
  Container,
  Heading,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
} from "@chakra-ui/react"
import { useQueryClient } from "@tanstack/react-query"
import { createFileRoute, useNavigate, redirect } from "@tanstack/react-router"
import { z } from "zod"
import { useState } from "react"

import type { UserPublic } from "../../client"
import Appearance from "../../components/UserSettings/Appearance"
import ChangePassword from "../../components/UserSettings/ChangePassword"
import DeleteAccount from "../../components/UserSettings/DeleteAccount"
import UserInformation from "../../components/UserSettings/UserInformation"
import UserTokens from "../../components/UserSettings/UserTokens"
import Subscription from "../../components/UserSettings/Subscription"
import { pageWidthNoSidebar } from "../../lib/layout"
import { isLoggedIn } from "../../hooks/useAuth"

const tabsConfig = [
  { title: "My profile", component: UserInformation, slug: "profile" },
  { title: "Subscription", component: Subscription, slug: "subscription" },
  { title: "Password", component: ChangePassword, slug: "password" },
  { title: "Appearance", component: Appearance, slug: "appearance" },
  { title: "Tokens", component: UserTokens, slug: "tokens" },
  { title: "Danger zone", component: DeleteAccount, slug: "delete-account" },
]

const tabSearchSchema = z.object({ tab: z.string().catch("") })

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  validateSearch: (search) => tabSearchSchema.parse(search),
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }
  },
})

function UserSettings() {
  const queryClient = useQueryClient()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig.slice(0, 5)
    : tabsConfig
  const { tab } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  let initialTabIndex = 0
  if (tab) {
    finalTabs.forEach((tabDef, index) => {
      if (tab === tabDef.slug) {
        initialTabIndex = index
      }
    })
  }
  const [activeTabIndex, setActiveTabIndex] = useState(initialTabIndex)
  const handleTabChange = (index: number) => {
    setActiveTabIndex(index)
    navigate({ search: { tab: finalTabs[index].slug } })
  }

  return (
    <Container maxW={pageWidthNoSidebar}>
      <Heading size="lg" textAlign={{ base: "center", md: "left" }} py={12}>
        Settings
      </Heading>
      <Tabs
        variant="enclosed"
        index={activeTabIndex}
        onChange={handleTabChange}
      >
        <TabList>
          {finalTabs.map((tab, index) => (
            <Tab key={index}>{tab.title}</Tab>
          ))}
        </TabList>
        <TabPanels>
          {finalTabs.map((tab, index) => (
            <TabPanel key={index}>
              <tab.component />
            </TabPanel>
          ))}
        </TabPanels>
      </Tabs>
    </Container>
  )
}
