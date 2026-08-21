import { CheckCircleIcon, ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Checkbox,
  Flex,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Heading,
  HStack,
  Icon,
  Image,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalOverlay,
  Progress,
  Radio,
  RadioGroup,
  Select,
  Stack,
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
import { useState } from "react"
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
import BrowseDatasets from "../../components/Datasets/BrowseDatasets"
import NewDataset from "../../components/Datasets/NewDataset"
import UploadDataset from "../../components/Datasets/UploadDataset"
import FilterableSelect from "../../components/Common/FilterableSelect"
import FigureStudio from "../../components/Figures/FigureStudio"
import CommandBlock from "../../components/Onboarding/CommandBlock"
import ReproAudit from "../../components/Onboarding/ReproAudit"
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
// Each field falls back to unset rather than throwing, so a hand-edited or
// stale URL lands on the first step instead of the error boundary.
const searchSchema = z.object({
  path: z.enum(["existing", "fresh", "overleaf"]).optional().catch(undefined),
  step: z.number().optional().catch(undefined),
  // "owner/name" once the project exists, which is what the later steps act
  // on. Present from step 2 onward.
  project: z.string().optional().catch(undefined),
  // Whether the existing project is coming from a GitHub repo or a zip.
  // In the URL because connecting GitHub leaves the page and comes back,
  // and losing the choice there means picking it again.
  upload: z.boolean().optional().catch(undefined),
  // Same reason: connecting Zotero leaves the site entirely and returns
  // here, and coming back to a closed dialog reads as the click failing.
  overleaf_open: z.boolean().optional().catch(undefined),
  zotero_open: z.boolean().optional().catch(undefined),
  studio_open: z.boolean().optional().catch(undefined),
  // Which data dialog is open on the data step.
  data_open: z
    .enum(["enter", "upload", "import", "browse"])
    .optional()
    .catch(undefined),
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

type StepKey =
  | "path"
  | "name"
  | "audit"
  | "question"
  | "data"
  | "figure"
  | "paper"
  | "machine"

// The order the work happens in differs by where someone starts. A fresh
// project walks the research loop the template already embodies: question,
// data and a figure, the paper, then the machine that runs it. An imported
// project gets looked at before anything is asked of it. A project that
// starts from a paper links the paper before anything else.
const STEPS_BY_PATH: Record<StartPath, StepKey[]> = {
  fresh: ["path", "name", "question", "data", "figure", "paper", "machine"],
  existing: ["path", "name", "audit", "question", "machine"],
  overleaf: ["path", "name", "paper", "question", "data", "machine"],
}

const STEP_TITLES: Record<StepKey, string> = {
  path: "Where you're starting",
  name: "Name it",
  audit: "What we found",
  question: "The question",
  data: "Your data",
  figure: "A figure",
  paper: "Paper and references",
  machine: "Your machine",
}

const stepsFor = (path?: StartPath): StepKey[] =>
  path ? STEPS_BY_PATH[path] : ["path", "name"]

const TEMPLATES = [
  {
    value: "calkit/example-basic",
    label: "Basic: uv environment, Python analysis, LaTeX paper",
  },
  {
    value: "calkit/example-matlab",
    label: "MATLAB: scripts run in batch mode",
  },
  {
    value: "calkit/example-analytics",
    label: "Analytics: data processing and interactive figures",
  },
]

function StepHeader({ step, steps }: { step: number; steps: StepKey[] }) {
  const dimColor = useColorModeValue("gray.300", "gray.600")
  return (
    <Box mb={8}>
      <Progress
        value={((step + 1) / steps.length) * 100}
        size="xs"
        colorScheme="teal"
        borderRadius="full"
        mb={3}
      />
      <Flex gap={4} wrap="wrap">
        {steps.map((key, index) => (
          <Flex key={key} align="center" gap={1.5}>
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
              {STEP_TITLES[key]}
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
        A research project moves between reading, collecting data, analyzing it,
        and writing it up, and the pieces usually live in four different places.
        Calkit puts them in one project that stays a plain Git repo, so you can
        move between them without leaving. Nothing you set up here is trapped in
        Calkit, and all of it works offline.
      </Text>
      <StartPaths onSelect={onSelect} selected={path} source="wizard" />
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
  // Plenty of "projects in progress" aren't on GitHub yet, which is the
  // whole situation this path exists for. The file itself can't live in the
  // URL, but which route the user chose can.
  const { upload: fromUpload } = Route.useSearch()
  const navigate = Route.useNavigate()
  const setFromUpload = (value: boolean) =>
    navigate({ search: (prev) => ({ ...prev, upload: value || undefined }) })
  const [uploadFile, setUploadFile] = useState<File | null>(null)
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
      keep_template_history: false,
      git_repo_exists: isExisting,
      existing_repo: "",
    },
  })
  const mutation = useMutation({
    mutationFn: (data: ProjectFormValues) => {
      if (isExisting && Boolean(fromUpload)) {
        if (!uploadFile) {
          return Promise.reject(new Error("Choose a zip file to upload."))
        }
        return ProjectsService.postProjectUpload({
          bodyProjectsPostProjectUpload: {
            title: data.title,
            name:
              data.name ||
              data.title
                .toLowerCase()
                .replace(/\s+/g, "-")
                .replace(/[^\w-]+/g, ""),
            description: data.description || null,
            is_public: Boolean(data.is_public),
            file: uploadFile,
          },
        }).then((response) => response.data)
      }
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
        keep_template_history:
          !isExisting && Boolean(data.keep_template_history),
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
      mixpanel.track("Created new project", {
        onboarding: true,
        path,
        from_upload: isExisting && Boolean(fromUpload),
      })
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
  // The GitHub repos route is typed as raw JSON dictionaries, so the shape
  // is narrowed here rather than pretended at the boundary.
  const repos = (reposQuery.data ?? []) as unknown as {
    full_name: string
    private?: boolean
    description?: string | null
  }[]
  const repoOptions = repos.map((r) => ({
    value: r.full_name,
    hint: r.private ? "private" : undefined,
  }))
  const selectRepo = (fullName: string) => {
    const repo = repos.find((r) => r.full_name === fullName)
    setValue("git_repo_url", `https://github.com/${fullName}`)
    const repoName = fullName.split("/").at(-1) ?? ""
    setValue("name", repoName.toLowerCase())
    const spaced = repoName.replace(/[-_]+/g, " ").trim()
    if (spaced) {
      setValue("title", spaced.charAt(0).toUpperCase() + spaced.slice(1))
    }
    if (repo?.description) {
      setValue("description", repo.description)
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
          ? "Point Calkit at the repo. Nothing in it is moved or rewritten: " +
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
        <RadioGroup
          value={fromUpload ? "upload" : "repo"}
          onChange={(value) => setFromUpload(value === "upload")}
          mb={4}
        >
          <Stack>
            <Radio value="repo" colorScheme="teal">
              It's in a GitHub repo
            </Radio>
            <Radio value="upload" colorScheme="teal">
              It's only on my machine: upload a zip of the folder
            </Radio>
          </Stack>
        </RadioGroup>
      ) : null}
      {isExisting && !fromUpload ? (
        <FormControl mb={4}>
          <FormLabel htmlFor="existing_repo">Your GitHub repos</FormLabel>
          <FilterableSelect
            id="existing_repo"
            options={repoOptions}
            isLoading={reposQuery.isPending}
            placeholder="Start typing…"
            emptyMessage="No repo matches that."
            onSelect={selectRepo}
          />
          <FormHelperText>
            Yours and your organizations', most recently updated first. Not
            listed? Paste the URL below instead.
          </FormHelperText>
        </FormControl>
      ) : null}
      {isExisting && Boolean(fromUpload) ? (
        <FormControl isRequired mb={4}>
          <FormLabel htmlFor="upload">Project folder, zipped</FormLabel>
          <Input
            id="upload"
            type="file"
            accept=".zip,application/zip"
            p={1}
            onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
          />
          <FormHelperText>
            Up to 50 MB. A new GitHub repo is created for it, and the contents
            land as the first commit. Leave large data out and add it with DVC
            once the project is set up.
          </FormHelperText>
        </FormControl>
      ) : null}
      <FormControl isRequired isInvalid={!!errors.title} mb={4}>
        <FormLabel htmlFor="title">Title</FormLabel>
        <Input
          id="title"
          {...register("title", {
            required: "Title is required.",
            // Passed through register so it chains with the form's own
            // handler rather than replacing it.
            onChange: isExisting ? undefined : onTitleChange,
          })}
          placeholder="Ex: Coherent structures in high Reynolds number boundary layers"
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
            <option value="">Empty repo: I'll set it up myself</option>
          </Select>
        </FormControl>
      ) : null}
      {!isExisting ? (
        <FormControl mb={4}>
          <Checkbox {...register("keep_template_history")} colorScheme="teal">
            Keep the template's commit history
          </Checkbox>
          <FormHelperText>
            Off by default: your project starts from one commit holding the
            template's files, and calkit.yaml records which template and
            revision it came from.
          </FormHelperText>
        </FormControl>
      ) : null}
      <FormControl
        isInvalid={!!errors.git_repo_url}
        mb={4}
        display={isExisting && Boolean(fromUpload) ? "none" : undefined}
      >
        <FormLabel htmlFor="git_repo_url">GitHub repo URL</FormLabel>
        <Input
          id="git_repo_url"
          {...register("git_repo_url", {
            // The field is hidden in upload mode, where the repo is created
            // for the zip, so requiring it there would block submit with an
            // error nobody can see.
            required:
              isExisting && Boolean(fromUpload)
                ? false
                : "GitHub repo URL is required.",
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
          <Button
            as={Link}
            href={`https://github.com/apps/${appName}/installations/new`}
            isExternal
            size="sm"
            variant="primary"
          >
            Install on GitHub <ExternalLinkIcon ml={1} />
          </Button>
        </Box>
      ) : null}
    </Box>
  )
}

interface QuestionFormValues {
  question: string
  hypothesis: string
}

const QUESTION_PLACEHOLDER =
  "Does the wake recover faster at higher tip speed ratios?"

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
          placeholder={QUESTION_PLACEHOLDER}
          rows={2}
        />
        {errors.question ? (
          <FormErrorMessage>{errors.question.message}</FormErrorMessage>
        ) : null}
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
        <Button
          variant="ghost"
          onClick={() => {
            mixpanel.track("Skipped project wizard step", {
              step: "question",
            })
            onDone()
          }}
        >
          Skip for now
        </Button>
      </HStack>
    </Box>
  )
}

/** For an imported project: what's there, and what it would take. */
function AuditStep({
  accountName,
  projectName,
  onDone,
}: {
  accountName: string
  projectName: string
  onDone: () => void
}) {
  return (
    <>
      <Heading size="lg" mb={2}>
        Here's what we found
      </Heading>
      <Text color="ui.dim" mb={6}>
        Nothing was moved or rewritten. This is the project as it stands, read
        the way a stranger trying to reproduce it would read it. Each gap
        becomes an item on the project's setup list, with a button that closes
        it.
      </Text>
      <Box mb={6}>
        <ReproAudit accountName={accountName} projectName={projectName} />
      </Box>
      <Button variant="primary" onClick={onDone}>
        Continue
      </Button>
    </>
  )
}

/** Where the data comes from: typed in, uploaded, imported, or found. */
function DataStep({
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
  const { data_open: dataOpen } = Route.useSearch()
  const navigate = Route.useNavigate()
  const setDataOpen = (
    value: "enter" | "upload" | "import" | "browse" | undefined,
  ) => navigate({ search: (prev) => ({ ...prev, data_open: value }) })
  const datasetsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "datasets"],
    queryFn: () =>
      ProjectsService.getProjectDatasets({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
  })
  const datasets = datasetsQuery.data ?? []
  const options: {
    key: "enter" | "upload" | "import" | "browse"
    title: string
    body: string
  }[] = [
    {
      key: "enter",
      title: "Type it in",
      body: "Readings, a tally, a table from a paper. A small grid that saves as a CSV you collected.",
    },
    {
      key: "upload",
      title: "Upload a file",
      body: "A CSV, a spreadsheet, an HDF5 file, an archive. Small files go in Git, large ones in DVC.",
    },
    {
      key: "import",
      title: "Import by DOI, URL, or Git",
      body: "Zenodo, Figshare, a download link, or a path in a repo at a pinned commit. Fetched now, origin recorded.",
    },
    {
      key: "browse",
      title: "Find a dataset on Calkit",
      body: "Data another project on this hub already published, linked back to where it came from.",
    },
  ]
  return (
    <>
      <Heading size="lg" mb={2}>
        Bring in your data
      </Heading>
      <Text color="ui.dim" mb={5}>
        Every figure traces back to data, so the data comes first. Each of these
        records where it came from, which is what lets anyone follow a result
        back to its source later. Data your pipeline produces doesn't need
        adding here; its stage is its source.
      </Text>
      <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3} mb={5}>
        {options.map((option) => (
          <Box
            key={option.key}
            as="button"
            type="button"
            textAlign="left"
            borderWidth={1}
            borderColor={borderColor}
            borderRadius="lg"
            bg={cardBg}
            p={4}
            _hover={{ borderColor: "ui.main", shadow: "md" }}
            onClick={() => {
              mixpanel.track("Chose data source in wizard", {
                source: option.key,
              })
              setDataOpen(option.key)
            }}
          >
            <Heading size="sm" mb={1}>
              {option.title}
            </Heading>
            <Text fontSize="sm" color="ui.dim">
              {option.body}
            </Text>
          </Box>
        ))}
      </SimpleGrid>
      {datasets.length ? (
        <Box mb={5} fontSize="sm">
          <Text fontWeight="semibold" mb={1}>
            In the project so far
          </Text>
          {datasets.map((d) => (
            <Flex key={d.path} gap={2} align="center">
              <Icon as={CheckCircleIcon} color="ui.success" boxSize={3} />
              <Text>
                {d.title || d.path}
                {d.title ? (
                  <Text as="span" color="ui.dim">
                    {" "}
                    ({d.path})
                  </Text>
                ) : null}
              </Text>
            </Flex>
          ))}
        </Box>
      ) : null}
      <HStack spacing={3}>
        <Button variant="primary" onClick={onDone}>
          Continue
        </Button>
        <Text fontSize="sm" color="ui.dim">
          You can add more from the datasets page any time.
        </Text>
      </HStack>
      {dataOpen === "enter" || dataOpen === "import" ? (
        <NewDataset
          key={dataOpen}
          isOpen
          onClose={() => setDataOpen(undefined)}
          ownerName={accountName}
          projectName={projectName}
          defaultSource={dataOpen === "enter" ? "enter" : "doi"}
        />
      ) : null}
      {dataOpen === "upload" ? (
        <UploadDataset
          isOpen
          onClose={() => setDataOpen(undefined)}
          ownerName={accountName}
          projectName={projectName}
        />
      ) : null}
      {dataOpen === "browse" ? (
        <BrowseDatasets
          isOpen
          onClose={() => setDataOpen(undefined)}
          ownerName={accountName}
          projectName={projectName}
        />
      ) : null}
    </>
  )
}

/**
 * For a fresh project: the figure the template already produced, and the
 * studio to make the next one.
 *
 * The template's data, script, and figure are all in the repo, and the
 * figure is on the project page before anything has been installed. That
 * is the thing to show first: not a form, a result.
 */
function FigureStep({
  accountName,
  projectName,
  onDone,
}: {
  accountName: string
  projectName: string
  onDone: () => void
}) {
  const { studio_open: studioOpen } = Route.useSearch()
  const navigate = Route.useNavigate()
  const setStudioOpen = (open: boolean) =>
    navigate({
      search: (prev) => ({ ...prev, studio_open: open || undefined }),
    })
  const figuresQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "figures"],
    queryFn: () =>
      ProjectsService.getProjectFigures({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
  })
  const figures = figuresQuery.data?.items ?? []
  const shown = figures.find((f) => f.content || f.url)
  const datasetsQuery = useQuery({
    queryKey: ["projects", accountName, projectName, "datasets"],
    queryFn: () =>
      ProjectsService.getProjectDatasets({
        owner_name: accountName,
        project_name: projectName,
      }).then((response) => response.data),
    retry: false,
  })
  const dataset = datasetsQuery.data?.[0]
  const borderColor = useColorModeValue("gray.200", "gray.600")
  return (
    <>
      <Heading size="lg" mb={2}>
        {shown ? "Your project already makes a figure" : "Make a figure"}
      </Heading>
      <Text color="ui.dim" mb={5}>
        {shown
          ? "The template's pipeline collects data, analyzes it, and draws " +
            "this. It's on your project page now, and it traces back to the " +
            "script, the data, and the environment that made it. Edit any of " +
            "those and it rebuilds."
          : "Plot a dataset right here in the browser, then save it as a " +
            "pipeline stage with a real environment, so it's reproducible " +
            "from the start."}
      </Text>
      {shown ? (
        <Flex
          gap={5}
          mb={5}
          direction={{ base: "column", md: "row" }}
          align="flex-start"
        >
          <Box
            borderWidth={1}
            borderColor={borderColor}
            borderRadius="md"
            p={2}
            maxW={{ base: "100%", md: "55%" }}
          >
            <Image
              src={
                shown.content
                  ? `data:image/png;base64,${shown.content}`
                  : String(shown.url)
              }
              alt={shown.title}
              maxH="260px"
            />
          </Box>
          <Box fontSize="sm">
            <Text fontWeight="semibold">{shown.title}</Text>
            <Text color="ui.dim" mb={2}>
              {shown.path}
              {shown.stage ? `, from stage ${shown.stage}` : ""}
            </Text>
            {dataset ? (
              <Text color="ui.dim">
                Data: {dataset.path}
                {dataset.title ? ` (${dataset.title})` : ""}
              </Text>
            ) : null}
          </Box>
        </Flex>
      ) : null}
      <HStack spacing={3} mb={2}>
        <Button
          variant={shown ? "outline" : "primary"}
          onClick={() => {
            mixpanel.track("Opened figure studio", { source: "wizard" })
            setStudioOpen(true)
          }}
        >
          {shown ? "Make your own figure" : "New figure from data"}
        </Button>
        <Button variant={shown ? "primary" : "ghost"} onClick={onDone}>
          Continue
        </Button>
      </HStack>
      <Text fontSize="xs" color="ui.dim">
        The editor runs Python in your browser, nothing to install. Saving a
        plot from it adds a stage to the pipeline and an environment for it to
        run in.
      </Text>
      {studioOpen ? (
        <FigureStudio
          isOpen
          onClose={() => setStudioOpen(false)}
          ownerName={accountName}
          projectName={projectName}
          initialDataset={dataset?.path}
        />
      ) : null}
    </>
  )
}

/** The paper and the library: where the writing already lives. */
function PaperStep({
  path,
  accountName,
  projectName,
  onDone,
}: {
  path: StartPath
  accountName: string
  projectName: string
  onDone: () => void
}) {
  const cardBg = useColorModeValue("white", "ui.darkSlate")
  const borderColor = useColorModeValue("gray.200", "gray.600")
  const { overleaf_open: overleafOpen, zotero_open: zoteroOpen } =
    Route.useSearch()
  const navigate = Route.useNavigate()
  const setOpen = (key: "overleaf_open" | "zotero_open", open: boolean) =>
    navigate({ search: (prev) => ({ ...prev, [key]: open || undefined }) })
  const overleafModal = {
    isOpen: Boolean(overleafOpen),
    onOpen: () => setOpen("overleaf_open", true),
    onClose: () => setOpen("overleaf_open", false),
  }
  const zoteroModal = {
    isOpen: Boolean(zoteroOpen),
    onOpen: () => setOpen("zotero_open", true),
    onClose: () => setOpen("zotero_open", false),
  }
  const isOverleaf = path === "overleaf"
  const isFresh = path === "fresh"
  return (
    <>
      <Heading size="lg" mb={2}>
        {isOverleaf ? "Link the paper" : "The paper and the references"}
      </Heading>
      <Text color="ui.dim" mb={6}>
        {isOverleaf
          ? "The Overleaf project you're writing in becomes a folder in this " +
            "repo and syncs both ways. Once the analysis lives alongside it, " +
            "its figures come from the pipeline instead of your downloads."
          : isFresh
            ? "The template includes a LaTeX paper that builds from the " +
              "pipeline, so a figure that changes reaches the PDF on the " +
              "next run. If you'd rather write in Overleaf, link that " +
              "instead; either way the references can come from Zotero."
            : "Your paper stays in Overleaf and your library stays in " +
              "Zotero. Linking them here is what makes the figures and " +
              "citations in them come from the pipeline."}
      </Text>
      {isFresh ? (
        <Box
          borderWidth={1}
          borderColor={borderColor}
          borderRadius="lg"
          bg={cardBg}
          p={4}
          mb={4}
          fontSize="sm"
        >
          <Text fontWeight="semibold" mb={1}>
            paper/paper.tex builds paper/paper.pdf
          </Text>
          <Text color="ui.dim" mb={3}>
            Edit it in the browser with a live preview, or in any editor once
            it's on your machine.
          </Text>
          <Button
            size="sm"
            as={RouterLink}
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            to={`/${accountName}/${projectName}/publications` as any}
          >
            Open the paper
          </Button>
        </Box>
      ) : null}
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
          <Button
            size="sm"
            variant={isOverleaf ? "primary" : "outline"}
            onClick={overleafModal.onOpen}
          >
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
          <Button size="sm" variant="outline" onClick={zoteroModal.onOpen}>
            Import a collection
          </Button>
        </Box>
      </SimpleGrid>
      <HStack spacing={3}>
        <Button variant="primary" onClick={onDone}>
          Continue
        </Button>
        <Text fontSize="sm" color="ui.dim">
          Both are available later from the project page.
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
        environments, and moves results between your machine and here, and every
        bit of it works with the hub closed.
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
          2. Clone the project
        </Text>
        <CommandBlock command={`calkit clone ${accountName}/${projectName}`} />
        <Text fontSize="sm" color="ui.dim" mt={2}>
          The first run opens a browser to sign you in, so there's no separate
          login step.
        </Text>
      </Box>
      <Box mb={5}>
        <Text fontWeight="semibold" mb={2}>
          3. Run it
        </Text>
        <CommandBlock command='calkit run -m "Run pipeline"' />
        <Text fontSize="sm" color="ui.dim" mt={2}>
          The message tells it to push what the run produced back here, where
          the project page picks it up.
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
          : "Waiting to see Calkit running locally. This check is optional."}
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
  const steps = stepsFor(path)
  const step = Math.min(Math.max(stepParam ?? 0, 0), steps.length - 1)
  const current = steps[step]
  const [accountName, projectName] = (project ?? "").split("/")
  const goTo = (next: Partial<z.infer<typeof searchSchema>>) => {
    if (next.step !== undefined && next.step !== step) {
      // The whole point of the wizard is knowing where people stop, which
      // needs an event per transition rather than only at the end.
      const nextSteps = stepsFor(next.path ?? path)
      mixpanel.track("Moved through project wizard", {
        from_step: current,
        to_step: nextSteps[next.step] ?? "unknown",
        path: next.path ?? path,
        direction: next.step > step ? "forward" : "back",
      })
    }
    navigate({ search: (prev) => ({ ...prev, ...next }) })
  }
  const advance = () => goTo({ step: step + 1 })
  // Closing lands on the project once there is one, so backing out of the
  // optional steps doesn't feel like abandoning what was already created.
  const close = () => {
    mixpanel.track("Closed project wizard", {
      step: current,
      path,
      has_project: Boolean(project),
    })
    return navigate({
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      to: (project ? `/${accountName}/${projectName}` : "/") as any,
    })
  }
  const onCreated = (created: ProjectPublic) =>
    goTo({
      step: 2,
      project: `${created.owner_account_name}/${created.name}`,
    })
  let body
  if (current === "path" || !path) {
    body = (
      <ChoosePathStep
        path={path}
        onSelect={(chosen) => goTo({ path: chosen, step: 1 })}
      />
    )
  } else if (current === "name" || !accountName || !projectName) {
    // A link into a later step without a project has nothing to act on, so
    // render the step that creates one rather than steps that would 404.
    body = <NameItStep path={path} onCreated={onCreated} />
  } else if (current === "audit") {
    body = (
      <AuditStep
        accountName={accountName}
        projectName={projectName}
        onDone={advance}
      />
    )
  } else if (current === "question") {
    body = (
      <QuestionStep
        accountName={accountName}
        projectName={projectName}
        onDone={advance}
      />
    )
  } else if (current === "data") {
    body = (
      <DataStep
        accountName={accountName}
        projectName={projectName}
        onDone={advance}
      />
    )
  } else if (current === "figure") {
    body = (
      <FigureStep
        accountName={accountName}
        projectName={projectName}
        onDone={advance}
      />
    )
  } else if (current === "paper") {
    body = (
      <PaperStep
        path={path}
        accountName={accountName}
        projectName={projectName}
        onDone={advance}
      />
    )
  } else {
    body = <MachineStep accountName={accountName} projectName={projectName} />
  }
  // Once the project exists there's no going back to the step that made it.
  const canGoBack = step > 0 && !(project && step === 2)
  return (
    // A modal rather than a page, since starting a project is something you
    // step into and back out of. The route stays real so each step keeps its
    // URL: a refresh, the back button, and the trips out to GitHub, Zotero,
    // and Overleaf all come back to the step they left.
    <Modal
      isOpen
      onClose={close}
      size="3xl"
      scrollBehavior="inside"
      closeOnOverlayClick={false}
      isCentered
    >
      <ModalOverlay />
      <ModalContent>
        <ModalCloseButton />
        <ModalBody px={{ base: 6, md: 10 }} py={8}>
          <StepHeader step={step} steps={steps} />
          {body}
        </ModalBody>
        <ModalFooter>
          <Flex width="100%" align="center">
            {canGoBack ? (
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
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}
