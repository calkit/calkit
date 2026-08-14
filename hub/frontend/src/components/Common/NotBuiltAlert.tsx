import {
  Alert,
  AlertIcon,
  Box,
  Code,
  IconButton,
  Text,
  Tooltip,
  useClipboard,
} from "@chakra-ui/react"
import type { ReactNode } from "react"
import { FiCheck, FiCopy } from "react-icons/fi"

// A full-width command block with a copy button in its right side, like a
// fenced code block on GitHub.
export function CommandBlock({ command }: { command: string }) {
  const { onCopy, hasCopied } = useClipboard(command)
  return (
    <Box position="relative" width="100%">
      <Code
        display="block"
        whiteSpace="pre"
        overflowX="auto"
        width="100%"
        py={2}
        pl={2}
        // Keep the command clear of the copy button, which floats above it.
        pr={10}
      >
        {command}
      </Code>
      <Tooltip label={hasCopied ? "Copied" : "Copy"} closeOnClick={false}>
        <IconButton
          aria-label="Copy command"
          icon={hasCopied ? <FiCheck /> : <FiCopy />}
          size="xs"
          variant="ghost"
          onClick={onCopy}
          position="absolute"
          right={1}
          top="50%"
          transform="translateY(-50%)"
        />
      </Tooltip>
    </Box>
  )
}

interface NotBuiltAlertProps {
  // What's missing, e.g. "publication" or "presentation".
  kind: string
  // The pipeline stage that builds it, if known.
  stage?: string | null
  // Path to the output, used in the commit message.
  path: string
  // Optional element rendered alongside the message, e.g. an "Edit" button.
  action?: ReactNode
}

// Shown when an artifact has no content because the pipeline hasn't been run
// and its output pushed, with the command that will do so.
function NotBuiltAlert({ kind, stage, path, action }: NotBuiltAlertProps) {
  // Target the stage when we know it so only that part of the pipeline runs,
  // with a commit message naming the output.
  const runCmd = stage
    ? `calkit run ${stage} -m "Compile ${path}"`
    : 'calkit run -m "Run pipeline"'
  return (
    <Alert mt={2} status="warning" borderRadius="xl">
      <AlertIcon />
      <Box flex={1} minW={0}>
        <Text mb={2}>
          No content found. Perhaps the {kind} hasn't been built and pushed yet?
          To build, commit, and push it, execute this in the project folder:
        </Text>
        <CommandBlock command={runCmd} />
      </Box>
      {action}
    </Alert>
  )
}

export default NotBuiltAlert
