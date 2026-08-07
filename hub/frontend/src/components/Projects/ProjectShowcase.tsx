import { Badge, Box, Button, Code, HStack, Icon, Text } from "@chakra-ui/react"
import { MdEdit } from "react-icons/md"

import useProject from "../../hooks/useProject"
import LoadingSpinner from "../Common/LoadingSpinner"
import Tooltip from "../Common/Tooltip"
import Markdown from "../Common/Markdown"
import FigureView from "../Figures/FigureView"
import NotebookView from "../Notebooks/NotebookView"
import PublicationView from "../Publications/PublicationView"

interface ProjectShowcaseProps {
  ownerName: string
  projectName: string
  gitRef?: string
  // Provided (with write access, on the live view) to let members open a
  // publication's LaTeX source in the in-browser editor.
  onEditLatex?: (texPath: string, deps?: string[] | null) => void
}

function ProjectShowcase({
  ownerName,
  projectName,
  gitRef,
  onEditLatex,
}: ProjectShowcaseProps) {
  const { showcaseRequest } = useProject(ownerName, projectName, gitRef)
  return (
    <>
      {showcaseRequest.isPending ? (
        <LoadingSpinner height="100px" />
      ) : showcaseRequest.data ? (
        <>
          {showcaseRequest.data.elements.map((item, index) => (
            // eslint-disable-next-line react/no-array-index-key
            <Box mt={3} key={index}>
              {"figure" in item ? (
                <FigureView figure={item.figure} />
              ) : "publication" in item ? (
                <Box height="600px">
                  <PublicationView
                    publication={item.publication}
                    toolbarAction={
                      item.publication.stage_status?.status === "stale" ||
                      onEditLatex ? (
                        <HStack spacing={2}>
                          {item.publication.stage_status?.status ===
                            "stale" && (
                            <Tooltip label="This publication is out of date. Re-run the pipeline to rebuild it.">
                              <Badge colorScheme="orange">Stale</Badge>
                            </Tooltip>
                          )}
                          {onEditLatex && (
                            <Button
                              size="xs"
                              variant="ghost"
                              onClick={() =>
                                onEditLatex(
                                  item.publication.path.replace(
                                    /\.[^/.]+$/,
                                    ".tex",
                                  ),
                                  item.publication.stage_info?.deps,
                                )
                              }
                            >
                              <Icon as={MdEdit} mr={1} />
                              Edit LaTeX
                            </Button>
                          )}
                        </HStack>
                      ) : null
                    }
                  />
                </Box>
              ) : "text" in item ? (
                <Text>{item.text}</Text>
              ) : "markdown" in item ? (
                <Markdown>{item.markdown}</Markdown>
              ) : "yaml" in item ? (
                <Code whiteSpace="pre" width="100%" overflow="auto" p={2}>
                  {item.yaml}
                </Code>
              ) : "notebook" in item ? (
                <Box height="600px">
                  <NotebookView notebook={item.notebook} />
                </Box>
              ) : (
                ""
              )}
            </Box>
          ))}
        </>
      ) : (
        ""
      )}
    </>
  )
}

export default ProjectShowcase
