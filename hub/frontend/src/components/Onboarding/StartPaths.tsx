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
import type { IconType } from "react-icons"
import { FaBroom, FaLeaf, FaSeedling } from "react-icons/fa"

export type StartPath = "existing" | "fresh" | "overleaf"

interface PathOption {
  path: StartPath
  icon: IconType
  title: string
  description: string
}

/**
 * Nobody arrives wanting "a project." They arrive with scripts scattered
 * across a laptop, a shared drive, and an Overleaf tab, or with an idea and
 * a wish not to end up there again. Naming those situations lets someone
 * recognize themselves rather than guess which button is for them.
 */
export const START_PATHS: PathOption[] = [
  {
    path: "existing",
    icon: FaBroom,
    title: "Get a grip on a project in progress",
    description:
      "Scripts on your laptop, data on a shared drive, figures pasted into " +
      "Overleaf. Bring it under one roof and find out what it would take " +
      "to reproduce.",
  },
  {
    path: "fresh",
    icon: FaSeedling,
    title: "Start clean and stay that way",
    description:
      "Environment, pipeline, and paper wired together from the first " +
      "commit, so you spend your attention on the question instead of the " +
      "plumbing.",
  },
  {
    path: "overleaf",
    icon: FaLeaf,
    title: "Start from the paper you're writing",
    description:
      "Link the Overleaf project you already have, then grow the analysis " +
      "behind it so its figures and numbers stop drifting out of date.",
  },
]

interface StartPathsProps {
  /** Where a card sends the user; the chosen path rides along in search. */
  to?: string
  /** Rendered instead of the link target, e.g. inside the wizard itself. */
  onSelect?: (path: StartPath) => void
  selected?: StartPath
  columns?: number
}

const StartPaths = ({
  to = "/new",
  onSelect,
  selected,
  columns = 3,
}: StartPathsProps) => {
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const hoverBorder = "ui.main"
  return (
    <SimpleGrid columns={{ base: 1, md: columns }} spacing={4}>
      {START_PATHS.map((option) => {
        const isSelected = selected === option.path
        const cardProps = onSelect
          ? { onClick: () => onSelect(option.path), cursor: "pointer" }
          : {
              as: RouterLink,
              to,
              // Step 1 is the form; the choice this card just made is what
              // step 0 exists to ask, so don't ask it twice.
              search: { path: option.path, step: 1 },
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
