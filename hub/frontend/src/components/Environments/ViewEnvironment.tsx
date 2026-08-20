import {
  Box,
  Code,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Tab,
  TabList,
  TabPanel,
  TabPanels,
  Tabs,
  Text,
} from "@chakra-ui/react"
import { dump as yamlDump } from "js-yaml"
import SyntaxHighlighter from "react-syntax-highlighter"
import { atomOneDark } from "react-syntax-highlighter/dist/esm/styles/hljs"

import type { Environment } from "../../client"

interface ViewEnvProps {
  environment: Environment
  isOpen: boolean
  onClose: () => void
}

/** Guess a highlighter language from a file name. */
const languageFor = (path: string): string => {
  const name = path.toLowerCase()
  if (name.endsWith(".json")) return "json"
  if (name.endsWith(".toml") || name.endsWith(".lock")) return "ini"
  if (name.endsWith(".yml") || name.endsWith(".yaml")) return "yaml"
  if (name.endsWith("dockerfile")) return "dockerfile"
  if (name.endsWith(".nix")) return "nix"
  return "yaml"
}

const CodePane = ({ content, path }: { content: string; path: string }) => (
  <Box borderRadius="md" overflow="hidden" fontSize="sm">
    <SyntaxHighlighter
      language={languageFor(path)}
      style={atomOneDark}
      customStyle={{ margin: 0, borderRadius: "8px", maxHeight: "60vh" }}
      showLineNumbers={false}
    >
      {content}
    </SyntaxHighlighter>
  </Box>
)

/**
 * The spec and the lock side by side.
 *
 * The spec is what was asked for; the lock is what that resolved to, and
 * it's the half that decides whether someone else gets the same environment.
 * Docker, venv, and conda lock once per platform, so there can be several.
 */
const ViewEnvironment = ({ environment, isOpen, onClose }: ViewEnvProps) => {
  const locks = environment.locks ?? []
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="3xl"
      isCentered
      scrollBehavior="inside"
    >
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>
          Environment: <Code fontSize="md">{environment.name}</Code>
        </ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <Tabs variant="enclosed" isLazy>
            <TabList>
              <Tab>Definition</Tab>
              {environment.file_content ? <Tab>Spec</Tab> : null}
              {locks.map((lock) => (
                <Tab key={lock.path}>
                  {locks.length === 1 ? "Lock" : lock.path.split("/").pop()}
                </Tab>
              ))}
            </TabList>
            <TabPanels>
              {/* Every kind has this, including the ones with no spec file
                  of their own (Docker by image, Slurm, PBS, MATLAB). */}
              <TabPanel px={0}>
                <Text fontSize="xs" color="ui.dim" mb={2}>
                  calkit.yaml
                </Text>
                <CodePane
                  content={yamlDump({
                    [environment.name]: environment.all_attrs,
                  })}
                  path="calkit.yaml"
                />
              </TabPanel>
              {environment.file_content ? (
                <TabPanel px={0}>
                  <Text fontSize="xs" color="ui.dim" mb={2}>
                    {environment.path}
                  </Text>
                  <CodePane
                    content={environment.file_content}
                    path={environment.path ?? ""}
                  />
                </TabPanel>
              ) : null}
              {locks.map((lock) => (
                <TabPanel key={lock.path} px={0}>
                  <Text fontSize="xs" color="ui.dim" mb={2}>
                    {lock.path}
                    {lock.truncated ? " (truncated)" : ""}
                  </Text>
                  <CodePane content={lock.content} path={lock.path} />
                </TabPanel>
              ))}
            </TabPanels>
          </Tabs>
          {locks.length === 0 ? (
            <Text fontSize="sm" color="ui.dim" mt={3}>
              No lock file yet. One is written the first time the environment is
              checked or run, and it's what pins the exact versions.
            </Text>
          ) : null}
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default ViewEnvironment
