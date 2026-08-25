import {
  Badge,
  Box,
  Button,
  Card,
  Code,
  Flex,
  Heading,
  IconButton,
  Icon,
  Link,
  SimpleGrid,
  Text,
} from "@chakra-ui/react"
import {
  Link as RouterLink,
  createFileRoute,
  useNavigate,
} from "@tanstack/react-router"
import { AiOutlinePython } from "react-icons/ai"
import { FaCube, FaDocker, FaPlus } from "react-icons/fa"
import { SiAnaconda } from "react-icons/si"
import { z } from "zod"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"
import NoArtifactFound from "../../../../../components/Common/NoArtifactFound"
import NewEnvironment from "../../../../../components/Environments/NewEnvironment"

import type { Environment } from "../../../../../client"
import ViewEnvironment from "../../../../../components/Environments/ViewEnvironment"
import useProject, {
  useProjectEnvironments,
} from "../../../../../hooks/useProject"

const environmentsSearchSchema = z.object({
  // Creating an environment is a form worth several minutes; a refresh or a
  // back button shouldn't discard it, and a link can open it directly.
  new_env_open: z.boolean().optional(),
  ref: z.string().optional(),
  name: z.string().optional(),
})

export const Route = createFileRoute(
  "/_layout/$accountName/$projectName/_layout/environments",
)({
  component: ProjectEnvs,
  validateSearch: (search) => environmentsSearchSchema.parse(search),
})

const getIcon = (envType: string) => {
  if (["uv", "uv-venv", "venv"].includes(envType)) {
    return AiOutlinePython
  }
  if (envType == "conda") {
    return SiAnaconda
  }
  if (envType == "docker") {
    return FaDocker
  }
  return FaCube
}

interface EnvCardProps {
  environment: Environment
  onView: (name: string) => void
}

const EnvCard = ({ environment, onView }: EnvCardProps) => {
  return (
    <>
      <Card key={environment.name} p={6} variant="elevated">
        <Flex alignItems="center" mb={2}>
          <Icon as={getIcon(environment.kind)} mr={1} />
          <Heading size="md">
            <Code px={1} py={0.5} maxW="100%" fontSize="large">
              {environment.name}
              {environment.imported_from ? (
                <Badge ml={1} bgColor="green.500">
                  imported
                </Badge>
              ) : (
                ""
              )}
            </Code>
          </Heading>
        </Flex>
        {environment.kind ? (
          <Text mb={1}>
            <strong>Kind:</strong> <Code>{environment.kind}</Code>
          </Text>
        ) : (
          ""
        )}
        {environment.path ? (
          <Text mb={1}>
            <strong>Path:</strong>{" "}
            <Code>
              <Link
                as={RouterLink}
                to={"../files"}
                search={{ path: environment.path } as any}
              >
                {environment.path}
              </Link>
            </Code>
          </Text>
        ) : (
          ""
        )}
        {environment.all_attrs.image ? (
          <Text mb={1}>
            <strong>Image:</strong>{" "}
            <Code>{environment.all_attrs.image as string}</Code>
          </Text>
        ) : (
          ""
        )}
        {environment.description ? (
          <Text>
            <strong>Description:</strong> {environment.description}
          </Text>
        ) : (
          ""
        )}
        <Flex mt={1.5}>
          {/* Every kind is viewable: the ones with no spec file of their own
              (Docker by image, Slurm, PBS) still have a calkit.yaml entry
              and often a lock. */}
          <Button
            variant="primary"
            size="xs"
            mr={2}
            onClick={() => onView(environment.name)}
          >
            View
          </Button>
        </Flex>
      </Card>
    </>
  )
}

function ProjectEnvsView() {
  const { accountName, projectName } = Route.useParams()
  const {
    ref,
    name: selectedEnvName,
    new_env_open: newEnvOpen,
  } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { environmentsRequest } = useProjectEnvironments(
    accountName,
    projectName,
    ref,
  )
  const { userHasWriteAccess } = useProject(accountName, projectName, ref)
  const openNewEnv = () =>
    navigate({ search: (prev) => ({ ...prev, new_env_open: true }) })
  const closeNewEnv = () =>
    navigate({ search: (prev) => ({ ...prev, new_env_open: undefined }) })
  const { isPending: environmentsPending, data: environments } =
    environmentsRequest

  const openEnv = (name: string) =>
    navigate({ search: (prev) => ({ ...prev, name }) })
  const closeEnv = () =>
    navigate({ search: (prev) => ({ ...prev, name: undefined }) })

  const selectedEnv = environments?.find((e) => e.name === selectedEnvName)

  return (
    <>
      <Flex align="center" mb={4} gap={2} wrap="wrap">
        <Heading size="md">Environments</Heading>
        {userHasWriteAccess && !ref ? (
          <>
            <IconButton
              aria-label="New environment"
              variant="primary"
              height="25px"
              width="9px"
              px={1}
              icon={<Icon as={FaPlus} fontSize="xs" />}
              onClick={openNewEnv}
            />
            <NewEnvironment
              isOpen={Boolean(newEnvOpen)}
              onClose={closeNewEnv}
            />
          </>
        ) : null}
      </Flex>
      {environmentsPending ? (
        <LoadingSpinner height="100vh" />
      ) : environments?.length ? (
        <Box>
          <SimpleGrid columns={[2, null, 3]} gap={6}>
            {environments?.map((environment) => (
              <EnvCard
                key={environment.name}
                environment={environment}
                onView={openEnv}
              />
            ))}
          </SimpleGrid>
        </Box>
      ) : (
        <NoArtifactFound
          icon={FaCube}
          title="No environments found"
          hint="An environment precisely describes what dependencies your code needs to run, so a collaborator, a reviewer, or future you can easily run it later without lots of manual setup."
          docsUrl="https://docs.calkit.org/environments/"
        >
          {/* The modal only mounts at the default ref, so the button
              would do nothing on a historical view */}
          {userHasWriteAccess && !ref ? (
            <Button mt={3} size="sm" variant="primary" onClick={openNewEnv}>
              Create an environment
            </Button>
          ) : null}
        </NoArtifactFound>
      )}
      {selectedEnv && (
        <ViewEnvironment
          environment={selectedEnv}
          isOpen={Boolean(selectedEnv)}
          onClose={closeEnv}
        />
      )}
    </>
  )
}

function ProjectEnvs() {
  return <ProjectEnvsView />
}
