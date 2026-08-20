import { Flex, Icon, Text } from "@chakra-ui/react"
import type { ReactNode } from "react"
import type { IconType } from "react-icons"

interface NoArtifactFoundProps {
  /** The same icon the sidebar uses for this kind, so the page is placed. */
  icon: IconType
  /** What's missing, e.g. "No figures found". */
  title: string
  /** One line on how to get one, shown smaller under the title. */
  hint?: ReactNode
  /** Anything to offer here, e.g. a button clearing the active filter. */
  children?: ReactNode
  height?: string
  /** Overrides the muted default, for a mark with a brand color. */
  iconColor?: string
}

/**
 * What a project page shows before it has anything to show.
 *
 * An empty page is the most common thing a new project has, so it's worth
 * being a real state rather than blank space: the icon says which page you
 * landed on, and the hint says how to fill it. Consistent across the
 * artifact pages so "nothing here yet" always looks the same, and never
 * reads as something having failed to load.
 */
const NoArtifactFound = ({
  icon,
  title,
  hint,
  children,
  height = "300px",
  iconColor,
}: NoArtifactFoundProps) => (
  <Flex
    direction="column"
    align="center"
    justify="center"
    height={height}
    color="gray.500"
    textAlign="center"
    px={6}
  >
    <Icon as={icon} fontSize="4xl" mb={3} color={iconColor} />
    <Text>{title}</Text>
    {hint ? (
      <Text fontSize="sm" mt={1} maxW="440px">
        {hint}
      </Text>
    ) : null}
    {children ? <>{children}</> : null}
  </Flex>
)

export default NoArtifactFound
