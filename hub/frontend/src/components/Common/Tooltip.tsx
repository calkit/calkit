import { Tooltip as ChakraTooltip, type TooltipProps } from "@chakra-ui/react"

// Hover delay (ms) before any tooltip opens, applied site-wide.
const TOOLTIP_OPEN_DELAY = 600

// Site-wide tooltip: Chakra's Tooltip with the global hover delay applied by
// default. Use this instead of importing Tooltip from Chakra directly so every
// tooltip opens after the same delay. A caller may still override openDelay.
export default function Tooltip(props: TooltipProps) {
  return <ChakraTooltip openDelay={TOOLTIP_OPEN_DELAY} {...props} />
}
