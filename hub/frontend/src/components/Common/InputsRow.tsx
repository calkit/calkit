/**
 * One labeled row in an artifact info panel listing the things that went
 * into it, each a link to where that input lives in the project.
 */
import { Box, Code, Link, Text } from "@chakra-ui/react"
import { Link as RouterLink } from "@tanstack/react-router"
import { Fragment } from "react"
import Tooltip from "./Tooltip"

export interface InputLink {
  key: string
  /** Route path, typed as plain string so the router's `to` accepts it. */
  to: string
  search?: Record<string, unknown>
  label: string
  /** A path shown on hover when the label is a title rather than a path. */
  tooltipPath?: string
  /** Render the label in monospace, for raw paths. */
  code?: boolean
}

export default function InputsRow({
  label,
  items,
}: {
  label: string
  items: InputLink[]
}) {
  if (items.length === 0) return null
  return (
    <Box fontSize="sm" mb={1} wordBreak="break-word">
      <Text as="span" fontWeight="semibold">
        {label}:
      </Text>{" "}
      {items.map((item, i) => {
        const link = (
          <Link as={RouterLink} to={item.to} search={item.search as any}>
            {item.code ? (
              <Code fontSize="xs" cursor="pointer">
                {item.label}
              </Code>
            ) : (
              item.label
            )}
          </Link>
        )
        return (
          <Fragment key={item.key}>
            {i > 0 && ", "}
            {item.tooltipPath ? (
              <Tooltip label={<Code fontSize="xs">{item.tooltipPath}</Code>}>
                <Box as="span">{link}</Box>
              </Tooltip>
            ) : (
              link
            )}
          </Fragment>
        )
      })}
    </Box>
  )
}
