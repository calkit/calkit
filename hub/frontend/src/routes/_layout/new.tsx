import { CheckCircleIcon, ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Checkbox,
  Container,
  Flex,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Heading,
  HStack,
  Icon,
  Input,
  Link,
  Progress,
  Select,
  SimpleGrid,
  Spacer,
  Text,
  Textarea,
  useColorModeValue,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { type SubmitHandler, useForm } from "react-hook-form"
import { FiCircle } from "react-icons/fi"
import { SiOverleaf, SiZotero } from "react-icons/si"
import { z } from "zod"

import {
  type ProjectPost,
  type ProjectPublic,
  ProjectsService,
  type UserPublic,
  UsersService,
} from "../../client"
import ConnectGitHubPrompt from "../../components/Common/ConnectGitHubPrompt"
import CommandBlock from "../../components/Onboarding/CommandBlock"
import StartPaths, {
  type StartPath,
} from "../../components/Onboarding/StartPaths"
import ImportOverleaf from "../../components/Publications/ImportOverleaf"
import ImportFromZoteroModal from "../../components/References/ImportFromZoteroModal"
import { isLoggedIn } from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { useLocalServer } from "../../hooks/useOnboarding"
import { appName } from "../../lib/core"
import { handleError } from "../../lib/errors"

// Each step's state lives in the URL so a refresh, a back button, or a trip
// out to GitHub or Zotero to connect an account all come back to the same
// place rather than to the start.
const searchSchema = z.object({
  path: z.enum(["existing", "fresh", "overleaf"]).optional(),
  step: z.number().optional(),
  // "owner/name" once the project exists, which is what the later steps act
  // on. Present from step 2 onward.
  project: z.string().optional(),
})

// Which start path the visitor picked before they had an account. The
// post-login redirect is a bare pathname (the router's `to` doesn't parse a
// query string), so the choice travels separately rather than being lost to
// signing up.
const PATH_STASH_KEY = "new_project_path"

export const Route = createFileRoute("/_layout/new")({
  component: NewProjectWizard,
  validateSearch: (search) => searchSchema.parse(search),
  beforeLoad: ({ search }) => {
    // Every path here ends in a GitHub repo, which needs an account.
    if (!isLoggedIn()) {
      localStorage.setItem("post_login_redirect", "/new")
      if (search.path) {
        sessionStorage.setItem(PATH_STASH_KEY, search.path)
      }
      throw redirect({ to: "/signup" })
    }
    if (!search.path) {
      const stashed = sessionStorage.getItem(PATH_STASH_KEY)
      sessionStorage.removeItem(PATH_STASH_KEY)
      if (
        stashed === "existing" ||
        stashed === "fresh" ||
        stashed === "overleaf"
      ) {
        throw redirect({ to: "/new", search: { path: stashed, step: 1 } })
      }
    }
  },
})

const STEP_TITLES = [
  "Where you're starting",
  "Name it",
  "The question",
  "Bring in your work",
  "Your machine",
]

const TEMPLATES = [
  {
    value: "calkit/example-basic",
    label: "Basic — Conda environment, Python analysis, LaTeX paper",
  },
  {
    value: "calkit/example-matlab",
    label: "MATLAB — scripts run in batch mode",
  },
  {
    value: "calkit/example-analytics",
    label: "Analytics — data processing and interactive figures",
  },
]

function StepHeader({ step }: { step: number }) {
  const dimColor = useColorModeValue("gray.300", "gray.600")
  return (
    <Box mb={8}>
      <Progress
        value={((step + 1) / STEP_TITLES.length) * 100}
        size="xs"
        colorScheme="teal"
        borderRadius="full"
        mb={3}
      />
      <Flex gap={4} wrap="wrap">
        {STEP_TITLES.map((title, index) => (
          <Flex key={title} align="center" gap={1.5}>
            <Icon
              as={index < step ? CheckCircleIcon : FiCircle}
              boxSize={3}
              color={
                index < step
                  ? "ui.success"
                  : index === step
                    ? "ui.main"
                    : dimColor
              }
            />
            <Text
              fontSize="xs"
              color={index === step ? "inherit" : "ui.dim"}
              fontWeight={index === step ? "semibold" : "normal"}
            >
              {title}
            </Text>
          </Flex>
        ))}
      </Flex>
    </Box>
  )
}

/** Step 1: which of the three situations the user is actually in. */
function ChoosePathStep({
  path,
  onSelect,
}: {
  path?: StartPath
  onSelect: (path: StartPath) => void
}) {
  return (
    <>
      <Heading size="lg" mb={2}>
        What are we starting with?
      </Heading>
      <Text color="ui.dim" mb={6}>
        Calkit puts the pieces of a research project — the data, the code, the
        environment it runs in, the figures, the paper — into one place that
        stays a plain Git repo. Nothing you set up here is trapped in Calkit,
        and all of it works offline.
      </Text>
      <StartPaths onSelect={onSelect} selected={path} />
    </>
  )
}

interface ProjectFormValues extends ProjectPost {
  existing_repo: string
}

/** Step 2: the form that actually creates the project. */
function NameItStep({
  path,
  onCreated,
}: {
  path: StartPath
  onCreated: (project: ProjectPublic) => void
}) {
  const isExisting = path === "existing"
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const githubAppModal = useDisclosure()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])
  const githubUsername = currentUser?.github_username ?? "your-name"
  // Creating a project needs a GitHub repo, which an account created through
  // Google or email can't have until it links a GitHub identity.
  const connectedAccountsQuery = useQuery({
    queryKey: ["user", "connected-accounts"],
    queryFn: () =>
      UsersService.getUserConnectedAccounts().then((response) => response.data),
  })
  const needsGitHub =
    connectedAccountsQuery.isSuccess && !connectedAccountsQuery.data?.github
  // Picking from a list beats pasting a URL for the cleanup path, which is
  // the whole point of that path: the repo already exists somewhere.
  const reposQuery = useQuery({
    queryKey: ["user", "github", "repos"],
    queryFn: () =>
      UsersService.getUserGithubRepos({ per_page: 100, page: 1 }).then(
        (response) => response.data,
      ),
    enabled: isExisting && !needsGitHub,
    retry: false,
  })
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<ProjectFormValues>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: "",
      name: "",
      description: "",
      git_repo_url: isExisting ? "" : `https://github.com/${githubUsername}/`,
      is_public: false,
      template: isExisting ? null : "calkit/example-basic",
      git_repo_exists: isExisting,
      existing_repo: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: ProjectFormValues) => {
      const post: ProjectPost = {
        title: data.title,
        name: data.name,
        description: data.description,
        is_public: data.is_public,
        git_repo_url: data.git_repo_url,
        git_repo_exists: isExisting,
        // An existing repo is imported as it stands; generating it from a
        // template would overwrite the work the user came here to clean up.
        template: isExisting ? null : data.template || null,
      }
      const gitName = String(post.git_repo_url).split("/").at(-1)
      if (gitName) {
        post.name = gitName.toLowerCase().replace(/\.git$/, "")
      }
      return ProjectsService.postProject({ projectPost: post }).then(
        (response) => response.data,
      )
    },
    onSuccess: (data: ProjectPublic) => {
      mixpanel.track("Created new project", { onboarding: true, path })
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      onCreated(data)
    },
    onError: (err: AxiosError) => {
      const detail = (err as any)?.response?.data?.detail
      const text = `${err?.message ?? ""} ${
        typeof detail === "string" ? detail : ""
      }`.toLowerCase()
      if (text.includes("calkit github app not enabled")) {
        githubAppModal.onOpen()
        return
      }
      handleError(err, showToast)
    },
  })
  const onTitleChange = (e: any) => {
    const projectName = String(e.target.value)
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^\w-]+/g, "")
    setValue(
      "git_repo_url",
      `https://github.com/${githubUsername}/${projectName}`,
    )
    setValue("name", projectName)
  }
  const onExistingRepoChange = (e: any) => {
    const repo = String(e.target.value)
    if (!repo) return
    setValue("git_repo_url", `https://github.com/${repo}`)
    const repoName = repo.split("/").at(-1) ?? ""
    setValue("name", repoName.toLowerCase())
    const spaced = repoName.replace(/[-_]+/g, " ").trim()
    if (spaced) {
      setValue("title", spaced.charAt(0).toUpperCase() + spaced.slice(1))
    }
  }
  const onSubmit: SubmitHandler<ProjectFormValues> = (data) =>
    mutation.mutate(data)
  if (needsGitHub) {
    return (
      <>
        <Heading size="lg" mb={4}>
          First, connect GitHub
        </Heading>
        <ConnectGitHubPrompt
          action="create a project"
          returnTo={`/new?path=${path}&step=1`}
        />
      </>
    )
  }
  return (
    <Box as="form" onSubmit={handleSubmit(onSubmit)}>
      <Heading size="lg" mb={2}>
        {isExisting ? "Which project are we cleaning up?" : "Name your project"}
      </Heading>
      <Text color="ui.dim" mb={6}>
        {isExisting
          ? "Point Calkit at the repo. Nothing in it is moved or rewritten — " +
            "we read what's there and show you what it would take to " +
            "reproduce."
          : path === "overleaf"
            ? "The repo is where the analysis behind the paper will live. " +
              "You'll link the Overleaf project to it in a moment, and its " +
              "figures start coming from the pipeline instead of your " +
              "downloads folder."
            : "You get a repo with an environment, a pipeline, and a paper " +
              "skeleton already wired together, so the first thing you do " +
              "is research rather than setup."}
      </Text>
      {isExisting ? (
        <FormControl mb={4}>
          <FormLabel htmlFor="existing_repo">Your GitHub repos</FormLabel>
          <Select
            id="existing_repo"
            placeholder={reposQuery.isPending ? "Loading…" : "Pick a repo…"}
            {...register("existing_repo", { onChange: onExistingRepoChange })}
          >
            {(reposQuery.data ?? []).map((repo: any) => (
              <option key={repo.full_name} value={repo.full_name}>
                {repo.full_name}
                {repo.private ? " (private)" : ""}
              </option>
            ))}
          </Select>
          <FormHelperText>
            Not listed? Paste the URL below instead.
          </FormHelperText>
        </FormControl>
      ) : null}
      <FormControl isRequired isInvalid={!!errors.title} mb={4}>
        <FormLabel htmlFor="title">Title</FormLabel>
        <Input
          id="title"
          {...register("title", { required: "Title is required." })}
          placeholder="Ex: Coherent structures in high Reynolds number boundary layers"
          onChange={isExisting ? undefined : onTitleChange}
          autoComplete="off"
        />
        {errors.title ? (
          <FormErrorMessage>{errors.title.message}</FormErrorMessage>
        ) : null}
      </FormControl>
      <FormControl mb={4}>
        <FormLabel htmlFor="description">Description</FormLabel>
        <Input
          id="description"
          {...register("description")}
          placeholder="One line on what this project is about"
          autoComplete="off"
        />
      </FormControl>
      {!isExisting ? (
        <FormControl mb={4}>
          <FormLabel htmlFor="template">Start from</FormLabel>
          <Select id="template" {...register("template")}>
            {TEMPLATES.map((template) => (
              <option key={template.value} value={template.value}>
                {template.label}
              </option>
            ))}
            <option value="">Empty repo — I'll set it up myself</option>
          </Select>
        </FormControl>
      ) : null}
      <FormControl isInvalid={!!errors.git_repo_url} mb={4}>
        <FormLabel htmlFor="git_repo_url">GitHub repo URL</FormLabel>
        <Input
          id="git_repo_url"
          {...register("git_repo_url", {
            required: "GitHub repo URL is required.",
          })}
          placeholder="https://github.com/your-name/your-repo"
          autoComplete="off"
        />
        {errors.git_repo_url ? (
          <FormErrorMessage>{errors.git_repo_url.message}</FormErrorMessage>
        ) : null}
      </FormControl>
      {!isExisting ? (
        <FormControl mb={6}>
          <Checkbox {...register("is_public")} colorScheme="teal">
            Make it public
          </Checkbox>
          <FormHelperText>
            A private project can be made public later. Going the other way
            isn't possible, so leave it private if you're unsure.
          </FormHelperText>
        </FormControl>
      ) : null}
      <Button
        variant="primary"
        type="submit"
        isLoading={isSubmitting || mutation.isPending}
      >
        Create project
      </Button>
      {githubAppModal.isOpen ? (
        <Box mt={4} p={4} borderRadius="md" borderWidth={1}>
          <Text mb={2}>
            The Calkit GitHub App needs access to your account or org before it
            can create the repo. Install it, then try again.
          </Text>
          <Link
            href={`https://github.com/apps/${appName}/installations/new`}
            isExternal
          >
            <Button size="sm" variant="primary">
              Install on GitHub <ExternalLinkIcon ml={1} />
            </Button>
          </Link>
        </Box>
      ) : null}
    </Box>
  )
}

interface QuestionFormValues {
  question: string
  hypothesis: string
}

const QUESTION_EXAMPLES = [
  "Does the wake recover faster at higher tip speed ratios?",
  "Is the atmospheric boundary layer more stable at night?",
  "Which of these three solvers gives the best accuracy per CPU hour?",
]

/** Step 3: the question the project exists to answer. */
function QuestionStep({
  accountName,
  projectName,
  onDone,
}: {
  accountName: string
  projectName: string
  onDone: () => void
}) {
  const showToast = useCustomToast()
  const queryClient = useQueryClient()
  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<QuestionFormValues>({
    mode: "onBlur",
    defaultValues: { question: "", hypothesis: "" },
  })
  const mutation = useMutation({
    mutationFn: (data: QuestionFormValues) =>
      ProjectsService.postProjectQuestion({
        owner_name: accountName,
        project_name: projectName,
        questionPost: {
          question: data.question,
          hypothesis: data.hypothesis || null,
        },
      }).then((response) => response.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "questions"],
      })
      onDone()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  return (
    <Box as="form" onSubmit={handleSubmit((data) => mutation.mutate(data))}>
      <Heading size="lg" mb={2}>
        What are you trying to find out?
      </Heading>
      <Text color="ui.dim" mb={6}>
        This sits at the top of the project page, and every figure and table you
        produce can be attached to it as evidence. Writing the hypothesis down
        now is what keeps the analysis from quietly becoming the hypothesis
        later.
      </Text>
      <FormControl isRequired isInvalid={!!errors.question} mb={4}>
        <FormLabel htmlFor="question">Research question</FormLabel>
        <Textarea
          id="question"
          {...register("question", { required: "A question is required." })}
          placeholder={QUESTION_EXAMPLES[0]}
          rows={2}
        />
        {errors.question ? (
          <FormErrorMessage>{errors.question.message}</FormErrorMessage>
        ) : (
          <FormHelperText>
            For example:{" "}
            {QUESTION_EXAMPLES.map((example, index) => (
              <span key={example}>
                {index > 0 ? " · " : ""}
                <Link
                  variant="blue"
                  onClick={() => setValue("question", example)}
                >
                  {example}
                </Link>
              </span>
            ))}
          </FormHelperText>
        )}
      </FormControl>
      <FormControl mb={6}>
        <FormLabel htmlFor="hypothesis">Hypothesis (optional)</FormLabel>
        <Textarea
          id="hypothesis"
          {...register("hypothesis")}
          placeholder="What you expect to find, and why"
          rows={2}
        />
      </FormControl>
      <HStack spacing={3}>
        <Button
          variant="primary"
          type="submit"
          isLoading={isSubmitting || mutation.isPending}
        >
          Save and continue
        </Button>
        <Button variant="ghost" onClick={onDone}>
          Skip for now
        </Button>
      </HStack>
    </Box>
  )
}

/** Step 4: the services the user's research already lives in. */
function ConnectStep({
  accountName,
  projectName,
  onDone,
}: {
  accountName: string
  projectName: string
  onDone: () => void
}) {
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const overleafModal = useDisclosure()
  const zoteroModal = useDisclosure()
  return (
    <>
      <Heading size="lg" mb={2}>
        Bring in what you already have
      </Heading>
      <Text color="ui.dim" mb={6}>
        Your paper stays in Overleaf and your library stays in Zotero. Calkit
        links them to the project so the figures and citations in them come from
        the pipeline instead of from a folder of exports.
      </Text>
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={4} mb={6}>
        <Box
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="lg"
          bg={cardBg}
          p={5}
        >
          <Flex align="center" gap={2} mb={2}>
            <Icon as={SiOverleaf} color="ui.main" />
            <Heading size="sm">Overleaf</Heading>
          </Flex>
          <Text fontSize="sm" color="ui.dim" mb={4}>
            Link the project you're writing in. Its .tex lives in a subfolder of
            your repo and syncs both ways.
          </Text>
          <Button size="sm" variant="primary" onClick={overleafModal.onOpen}>
            Link a paper
          </Button>
        </Box>
        <Box
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="lg"
          bg={cardBg}
          p={5}
        >
          <Flex align="center" gap={2} mb={2}>
            <Icon as={SiZotero} color="ui.main" />
            <Heading size="sm">Zotero</Heading>
          </Flex>
          <Text fontSize="sm" color="ui.dim" mb={4}>
            Import a collection into the project's .bib file, and keep it in
            step as you add references.
          </Text>
          <Button size="sm" variant="primary" onClick={zoteroModal.onOpen}>
            Import a collection
          </Button>
        </Box>
      </SimpleGrid>
      <HStack spacing={3}>
        <Button variant="primary" onClick={onDone}>
          Continue
        </Button>
        <Text fontSize="sm" color="ui.dim">
          You can do either of these later from the project page.
        </Text>
      </HStack>
      <ImportOverleaf
        isOpen={overleafModal.isOpen}
        onClose={overleafModal.onClose}
        ownerName={accountName}
        projectName={projectName}
      />
      <ImportFromZoteroModal
        isOpen={zoteroModal.isOpen}
        onClose={zoteroModal.onClose}
        ownerName={accountName}
        projectName={projectName}
      />
    </>
  )
}

const VSCODE_EXT_URL =
  "https://marketplace.visualstudio.com/items?itemName=Calkit.calkit-vscode"
const CHROME_EXT_URL =
  "https://chromewebstore.google.com/detail/idhdomgapfolnpffanajdckdaojencal"

/** Step 5: get the CLI onto the machine that will do the computing. */
function MachineStep({
  accountName,
  projectName,
}: {
  accountName: string
  projectName: string
}) {
  // Polled rather than fetched once, so the check turns green while the user
  // is still on this page running the commands above it.
  const { cliRunning } = useLocalServer()
  return (
    <>
      <Heading size="lg" mb={2}>
        Get it onto your machine
      </Heading>
      <Text color="ui.dim" mb={6}>
        This is where the work happens. The CLI runs the pipeline, manages
        environments, and moves results between your machine and here — and
        every bit of it works with the hub closed.
      </Text>
      <Box mb={5}>
        <Text fontWeight="semibold" mb={2}>
          1. Install the CLI
        </Text>
        <CommandBlock
          label="macOS, Linux, or Windows Git Bash"
          command="curl -LsSf install.calkit.org | sh"
        />
        <Link
          fontSize="xs"
          variant="blue"
          href="https://docs.calkit.org/installation/"
          isExternal
        >
          Windows PowerShell, pip, uv, and Nix <ExternalLinkIcon mb={0.5} />
        </Link>
      </Box>
      <Box mb={5}>
        <Text fontWeight="semibold" mb={2}>
          2. Connect it to the hub and clone the project
        </Text>
        <CommandBlock command="calkit hub login" />
        <Box mt={2}>
          <CommandBlock
            command={`calkit clone ${accountName}/${projectName}`}
          />
        </Box>
      </Box>
      <Box mb={5}>
        <Text fontWeight="semibold" mb={2}>
          3. Run it
        </Text>
        <CommandBlock command="calkit run" />
        <Text fontSize="sm" color="ui.dim" mt={2}>
          Then <code>calkit save -am "Run pipeline"</code> pushes the results
          back here, where the project page picks them up.
        </Text>
      </Box>
      <Flex
        align="center"
        gap={2}
        mb={6}
        fontSize="sm"
        color={cliRunning ? "ui.success" : "ui.dim"}
      >
        <Icon as={cliRunning ? CheckCircleIcon : FiCircle} />
        {cliRunning
          ? "Calkit is running on this machine."
          : "Waiting to see Calkit running locally — this check is optional."}
      </Flex>
      <Box mb={8}>
        <Text fontWeight="semibold" mb={2}>
          Optional: work where you already work
        </Text>
        <HStack spacing={4} wrap="wrap">
          <Link fontSize="sm" variant="blue" href={VSCODE_EXT_URL} isExternal>
            VS Code extension <ExternalLinkIcon mb={0.5} />
          </Link>
          <Link
            fontSize="sm"
            variant="blue"
            href="https://docs.calkit.org/jupyterlab/"
            isExternal
          >
            JupyterLab extension <ExternalLinkIcon mb={0.5} />
          </Link>
          <Link fontSize="sm" variant="blue" href={CHROME_EXT_URL} isExternal>
            Chrome extension <ExternalLinkIcon mb={0.5} />
          </Link>
        </HStack>
      </Box>
      <Button
        variant="primary"
        as={RouterLink}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        to={`/${accountName}/${projectName}` as any}
      >
        Go to my project
      </Button>
    </>
  )
}

function NewProjectWizard() {
  const navigate = useNavigate({ from: Route.fullPath })
  const { path, step: stepParam, project } = Route.useSearch()
  const step = stepParam ?? 0
  const [accountName, projectName] = (project ?? "").split("/")
  const goTo = (next: Partial<z.infer<typeof searchSchema>>) =>
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  let body
  if (step === 0 || !path) {
    body = (
      <ChoosePathStep
        path={path}
        onSelect={(chosen) => goTo({ path: chosen, step: 1 })}
      />
    )
  } else if (step === 1) {
    body = (
      <NameItStep
        path={path}
        onCreated={(created) =>
          goTo({
            step: 2,
            project: `${created.owner_account_name}/${created.name}`,
          })
        }
      />
    )
  } else if (!accountName || !projectName) {
    // A link into a later step without a project has nothing to act on, so
    // render the step that creates one rather than steps that would 404.
    body = (
      <NameItStep
        path={path}
        onCreated={(created) =>
          goTo({
            step: 2,
            project: `${created.owner_account_name}/${created.name}`,
          })
        }
      />
    )
  } else if (step === 2) {
    body = (
      <QuestionStep
        accountName={accountName}
        projectName={projectName}
        onDone={() => goTo({ step: 3 })}
      />
    )
  } else if (step === 3) {
    body = (
      <ConnectStep
        accountName={accountName}
        projectName={projectName}
        onDone={() => goTo({ step: 4 })}
      />
    )
  } else {
    body = <MachineStep accountName={accountName} projectName={projectName} />
  }
  return (
    <Container maxW="720px" pt={12} pb={16}>
      <StepHeader step={Math.min(step, STEP_TITLES.length - 1)} />
      {body}
      <Flex mt={10} align="center">
        {step > 0 && step !== 2 ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => goTo({ step: step - 1 })}
          >
            ← Back
          </Button>
        ) : null}
        <Spacer />
        {project ? (
          <Link
            as={RouterLink}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            to={`/${accountName}/${projectName}` as any}
            fontSize="sm"
            color="ui.dim"
          >
            Skip the rest and open the project →
          </Link>
        ) : null}
      </Flex>
    </Container>
  )
}
