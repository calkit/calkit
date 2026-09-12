import { CheckIcon, CopyIcon } from "@chakra-ui/icons"
import {
  Code,
  Flex,
  IconButton,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useState } from "react"

import useCustomToast from "../../hooks/useCustomToast"

interface CommandBlockProps {
  command: string
  /** Shown above the command, e.g. which shell it's for. */
  label?: string
}

/**
 * A shell command with a copy button.
 *
 * Onboarding asks people to run several of these, and retyping a command
 * out of a web page is exactly the kind of friction that ends a setup
 * halfway through.
 */
const CommandBlock = ({ command, label }: CommandBlockProps) => {
  const bg = useColorModeValue("gray.100", "gray.700")
  const showToast = useCustomToast()
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      showToast(
        "Copy failed",
        "Could not copy the command. Copy it manually.",
        "error",
      )
    }
  }
  return (
    <>
      {label ? (
        <Text fontSize="xs" color="ui.dim" mb={1}>
          {label}
        </Text>
      ) : null}
      <Flex align="center" bg={bg} borderRadius="md" pl={3} pr={1} py={1}>
        <Code
          bg="transparent"
          flex="1"
          fontSize="sm"
          overflowX="auto"
          whiteSpace="pre"
        >
          {command}
        </Code>
        <IconButton
          aria-label={`Copy: ${command}`}
          icon={copied ? <CheckIcon /> : <CopyIcon />}
          size="sm"
          variant="ghost"
          onClick={copy}
        />
      </Flex>
    </>
  )
}

export default CommandBlock
