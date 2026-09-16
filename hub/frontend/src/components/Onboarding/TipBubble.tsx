import {
  Box,
  Button,
  CloseButton,
  Flex,
  Popover,
  PopoverAnchor,
  PopoverArrow,
  PopoverBody,
  PopoverContent,
  Portal,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useLocation, useParams } from "@tanstack/react-router"
import mixpanel from "mixpanel-browser"
import { type ReactNode, useEffect } from "react"

import useProject from "../../hooks/useProject"
import useTips from "../../hooks/useTips"
import { onTipPage, TIPS, type TipId } from "../../lib/tips"

// Each tip is counted as seen once per page load, not once per render.
const seen = new Set<TipId>()

interface TipBubbleProps {
  tip: TipId
  /** "page" wraps the action itself; "nav" wraps the sidebar link to its
   * page, and only shows from other pages. */
  where: "page" | "nav"
  placement?: "right" | "bottom" | "top" | "left" | "bottom-start"
  /** Display of the wrapper; "block" for a full-width anchor. */
  display?: "inline-block" | "block"
  /** False to wrap without ever showing, e.g. on all but the first card. */
  when?: boolean
  /** Whether a click on the wrapped thing finishes the tip. Off for a
   * step on the way (opening a figure), where the bubble then moves to
   * the action itself. */
  markOnClick?: boolean
  children: ReactNode
}

/**
 * A little bubble over something worth trying, on a user's first project.
 *
 * It wraps the thing itself, so clicking through is the same click that
 * would have been made anyway. On the action it marks the tip done; on
 * the sidebar it only leads to the page, where the action's bubble takes
 * over.
 */
const TipBubble = ({
  tip: id,
  where,
  placement = "bottom",
  display = "inline-block",
  when = true,
  markOnClick = true,
  children,
}: TipBubbleProps) => {
  const { accountName, projectName } = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const { projectRequest, userHasWriteAccess } = useProject(
    accountName ?? "",
    projectName ?? "",
  )
  const { tip, markDone } = useTips(projectRequest.data?.id, userHasWriteAccess)
  const pathname = useLocation({ select: (l) => l.pathname })
  const bg = useColorModeValue("blue.600", "blue.400")
  const def = TIPS.find((t) => t.id === id)
  const onPage = def ? onTipPage(def, pathname) : false
  const active = when && tip?.id === id && (where === "page" ? onPage : !onPage)
  useEffect(() => {
    if (active && !seen.has(id)) {
      seen.add(id)
      mixpanel.track("Saw onboarding tip", { tip: id, where })
    }
  }, [active, id, where])
  if (!active || !def) return <>{children}</>
  return (
    <Popover
      isOpen
      placement={placement}
      closeOnBlur={false}
      autoFocus={false}
      arrowSize={10}
    >
      <PopoverAnchor>
        <Box
          display={display}
          onClickCapture={() => {
            if (where === "page" && markOnClick) markDone(id, "clicked")
            else mixpanel.track("Clicked onboarding tip", { tip: id, where })
          }}
        >
          {children}
        </Box>
      </PopoverAnchor>
      {/* Rendered at the body rather than inline: an anchor inside a
          card, a sidebar, or a scroll container would otherwise put the
          bubble in that element's stacking context, behind whatever
          comes next on the page. */}
      <Portal>
        <PopoverContent
          bg={bg}
          color="white"
          borderColor={bg}
          w="260px"
          zIndex="popover"
          boxShadow="lg"
        >
          <PopoverArrow bg={bg} />
          <PopoverBody px={3} py={2}>
            <Flex align="flex-start">
              <Box flex={1}>
                <Text fontWeight="semibold" fontSize="sm">
                  {def.title}
                </Text>
                <Text fontSize="xs" mt={0.5}>
                  {def.body}
                </Text>
              </Box>
              <CloseButton
                size="sm"
                ml={1}
                mr={-1}
                mt={-1}
                aria-label="Dismiss tip"
                onClick={() => markDone(id, "dismissed")}
              />
            </Flex>
            <Button
              size="xs"
              variant="link"
              color="whiteAlpha.800"
              mt={1}
              onClick={() => markDone(id, "dismissed")}
            >
              Got it
            </Button>
          </PopoverBody>
        </PopoverContent>
      </Portal>
    </Popover>
  )
}

export default TipBubble
