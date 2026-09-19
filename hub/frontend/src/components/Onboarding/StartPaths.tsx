import {
  Box,
  Flex,
  Heading,
  Icon,
  SimpleGrid,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { Link as RouterLink } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import type { IconType } from "react-icons"
import { FaBroom, FaLeaf, FaSeedling } from "react-icons/fa"

import type { StartPath } from "../../lib/onboarding"

interface PathOption {
  path: StartPath
  icon: IconType
  title: string
  description: string
}

const START_PATHS: PathOption[] = [
  {
    path: "existing",
    icon: FaBroom,
    title: "Clean up an existing project",
    description:
      "Link a GitHub repo or upload a ZIP of the files on your laptop.",
  },
  {
    path: "fresh",
    icon: FaSeedling,
    title: "Start fresh",
    description:
      "Build on a blank slate or a project template and follow best practices from day one.",
  },
  {
    path: "overleaf",
    icon: FaLeaf,
    title: "Start from an Overleaf project",
    description:
      "Connect the analysis to something you're already writing in Overleaf.",
  },
]

interface StartPathsProps {
  /** Where a card sends the user; the chosen path rides along in search. */
  to?: string
  /** Rendered instead of the link target, e.g. inside the wizard itself. */
  onSelect?: (path: StartPath) => void
  selected?: StartPath
  columns?: number
  /** Where these cards are shown, so the funnel can be split by entry point. */
  source?: string
}

const StartPaths = ({
  to = "/new",
  onSelect,
  selected,
  columns = 3,
  source = "unknown",
}: StartPathsProps) => {
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBorder = "ui.main"
  return (
    <SimpleGrid columns={{ base: 1, md: columns }} spacing={4}>
      {START_PATHS.map((option) => {
        const isSelected = selected === option.path
        const select = () => {
          mixpanel.track("Chose project start path", {
            path: option.path,
            source,
          })
          onSelect?.(option.path)
        }
        const cardProps = onSelect
          ? {
              // A div that acts as a button has to say so, and take the
              // keyboard, or the wizard's first step can't be tabbed through.
              role: "button",
              tabIndex: 0,
              "aria-pressed": isSelected,
              onClick: select,
              onKeyDown: (e: React.KeyboardEvent) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault()
                  select()
                }
              },
              cursor: "pointer",
            }
          : {
              as: RouterLink,
              to,
              onClick: () =>
                mixpanel.track("Chose project start path", {
                  path: option.path,
                  source,
                }),
              // The form opens with this source already picked.
              search: { path: option.path },
            }
        return (
          <Box
            key={option.path}
            {...(cardProps as any)}
            borderWidth={isSelected ? 2 : 1}
            borderColor={isSelected ? hoverBorder : borderColor}
            borderRadius="lg"
            bg={cardBg}
            p={5}
            textAlign="left"
            transition="all 0.15s"
            _hover={{ borderColor: hoverBorder, shadow: "md" }}
          >
            <Flex align="center" mb={2} gap={2}>
              <Icon as={option.icon} color="ui.main" boxSize={5} />
              <Heading size="sm">{option.title}</Heading>
            </Flex>
            <Text fontSize="sm" color="ui.dim">
              {option.description}
            </Text>
          </Box>
        )
      })}
    </SimpleGrid>
  )
}

export default StartPaths
