import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Card,
  Code,
  Flex,
  Heading,
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
import { FaCube, FaDocker } from "react-icons/fa"
import { SiAnaconda } from "react-icons/si"
import { z } from "zod"
import LoadingSpinner from "../../../../../components/Common/LoadingSpinner"

import type { Environment } from "../../../../../client"
import ViewEnvironment from "../../../../../components/Environments/ViewEnvironment"
import { useProjectEnvironments } from "../../../../../hooks/useProject"

const environmentsSearchSchema = z.object({
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
          {environment.file_content ? (
            <Button
              variant="primary"
              size="xs"
              mr={2}
              onClick={() => onView(environment.name)}
            >
              View
            </Button>
          ) : (
            ""
          )}
        </Flex>
      </Card>
    </>
  )
}

function ProjectEnvsView() {
  const { accountName, projectName } = Route.useParams()
  const { ref, name: selectedEnvName } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { environmentsRequest } = useProjectEnvironments(
    accountName,
    projectName,
    ref,
  )
  const { isPending: environmentsPending, data: environments } =
    environmentsRequest

  const openEnv = (name: string) =>
    navigate({ search: (prev) => ({ ...prev, name }) })
  const closeEnv = () =>
    navigate({ search: (prev) => ({ ...prev, name: undefined }) })

  const selectedEnv = environments?.find((e) => e.name === selectedEnvName)

  return (
    <>
      <Flex align="center" mb={2}>
        <Heading size="md">Environments</Heading>
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
        <Alert mt={2} status="warning" borderRadius="xl">
          <AlertIcon />
          This project has no environments defined.
        </Alert>
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
