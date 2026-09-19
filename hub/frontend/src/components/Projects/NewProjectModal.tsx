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
  HStack,
  Heading,
  Icon,
  Input,
  Link,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalOverlay,
  Radio,
  RadioGroup,
  Select,
  Stack,
  Text,
  useDisclosure,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"
import { useDebounce } from "use-debounce"

import {
  type ProjectPost,
  type ProjectPublic,
  ProjectsService,
  type UserPublic,
  UsersService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { appName } from "../../lib/core"
import { handleError } from "../../lib/errors"
import type { StartPath } from "../../lib/onboarding"
import ConnectGitHubPrompt from "../Common/ConnectGitHubPrompt"
import FilterableSelect from "../Common/FilterableSelect"

// Each step's state lives in the URL so a refresh, a back button, or a trip
// out to GitHub or Zotero to connect an account all come back to the same
// place rather than to the start.
// Each field falls back to unset rather than throwing, so a hand-edited or
// stale URL lands on the first step instead of the error boundary.
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
    label: "Analytics: notebook analysis, figures and tables",
  },
  {
    value: "calkit/example-r",
    label: "R: renv environment, R analysis, figures",
  },
  {
    value: "calkit/example-julia",
    label: "Julia: Julia environment, script and notebook, LaTeX paper",
  },
]

interface ProjectFormValues extends ProjectPost {
  existing_repo: string
}

/** Where the project comes from. One flat choice rather than a wizard. */
type Source = "github" | "upload" | "template" | "overleaf" | "empty"

const SOURCE_LABELS: { value: Source; label: string }[] = [
  { value: "github", label: "An existing GitHub repo" },
  { value: "overleaf", label: "An existing Overleaf project" },
  { value: "upload", label: "A zipped folder upload" },
  { value: "template", label: "A new project from a template" },
  { value: "empty", label: "An empty project" },
]

const SOURCE_FOR_PATH: Record<StartPath, Source> = {
  existing: "github",
  fresh: "template",
  overleaf: "overleaf",
}

/** The one form that creates a project. */
function NewProjectForm({
  initialPath,
  defaultTemplate,
  onCreated,
}: {
  initialPath?: StartPath
  /** Pre-selects a template, e.g. when using another project as one. */
  defaultTemplate?: string
  onCreated: (project: ProjectPublic) => void
}) {
  const [source, setSource] = useState<Source>(
    defaultTemplate
      ? "template"
      : initialPath
        ? SOURCE_FOR_PATH[initialPath]
        : "github",
  )
  // The mutation below still branches on these two, so the shape of the
  // request is unchanged by collapsing the wizard into one screen.
  const isExisting = source === "github" || source === "upload"
  const fromUpload = source === "upload"
  // Narrower than "a new repo": an empty project and an Overleaf one are
  // new repos too, but neither is generated from a template.
  const fromTemplate = source === "template"
  // The paper already carries a title, so asking for one here is asking the
  // user to copy it across. The server reads it from the main document.
  const fromOverleaf = source === "overleaf"
  const path: StartPath =
    source === "overleaf" ? "overleaf" : isExisting ? "existing" : "fresh"
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
  // the whole point of that path: the repo already exists somewhere. The
  // list starts as the most recently updated repos; once a couple of
  // characters are typed, the question goes to GitHub's search so a repo
  // past the listing cap is found too.
  const [repoSearch, setRepoSearch] = useState("")
  const [debouncedRepoSearch] = useDebounce(repoSearch.trim(), 300)
  const serverSearch =
    debouncedRepoSearch.length >= 2 ? debouncedRepoSearch : undefined
  const reposQuery = useQuery({
    queryKey: ["user", "github", "repos", serverSearch ?? ""],
    queryFn: () =>
      UsersService.getUserGithubRepos({
        per_page: 100,
        search: serverSearch,
      }).then((response) => response.data),
    enabled: isExisting && !needsGitHub,
    retry: false,
    placeholderData: (prev) => prev,
  })
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<ProjectFormValues>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: "",
      name: "",
      description: "",
      // The owner prefix is nearly always the user's own, so it's typed
      // for them; picking a repo from the list replaces it anyway.
      git_repo_url: `https://github.com/${githubUsername}/`,
      is_public: false,
      template: isExisting ? null : defaultTemplate ?? "calkit/example-basic",
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
        const title = data.title ?? ""
        return ProjectsService.postProjectUpload({
          bodyProjectsPostProjectUpload: {
            title,
            name:
              data.name ||
              title
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
        template: fromTemplate ? data.template || null : null,
        keep_template_history:
          fromTemplate && Boolean(data.keep_template_history),
        // Only sent for the one source that can supply a title of its own
        overleaf_project_url: fromOverleaf
          ? data.overleaf_project_url || null
          : null,
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
  // A repo under an organization needs two things a personal repo doesn't:
  // the org in Calkit (created on the way, which takes an admin of it on
  // GitHub) and the Calkit GitHub App installed for that org. Both are
  // checked here so the person finds out before the submit fails.
  const repoUrl = watch("git_repo_url") ?? ""
  const repoOwner = repoUrl.match(/github\.com\/([^/]+)\/./)?.[1] ?? ""
  const isOrgRepo =
    Boolean(repoOwner) &&
    repoOwner.toLowerCase() !== githubUsername.toLowerCase()
  const installationsQuery = useQuery({
    queryKey: ["user", "github-app-installations"],
    queryFn: () =>
      UsersService.getUserGithubAppInstallations().then(
        (response) => response.data,
      ),
    enabled: isOrgRepo && !needsGitHub,
    retry: false,
  })
  const installedFor = new Set(
    (installationsQuery.data?.installations ?? []).map((i: any) =>
      String(i?.account?.login ?? "").toLowerCase(),
    ),
  )
  const appInstalledForOrg = installedFor.has(repoOwner.toLowerCase())
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
          returnTo={`/new?path=${path}`}
        />
      </>
    )
  }
  return (
    <Box as="form" onSubmit={handleSubmit(onSubmit)}>
      {/* TODO: rewrite this heading */}
      <Heading size="lg" mb={2}>
        New project
      </Heading>
      <FormControl mb={5}>
        <FormLabel>Start from:</FormLabel>
        <RadioGroup
          value={source}
          onChange={(value) => setSource(value as Source)}
        >
          <Stack>
            {SOURCE_LABELS.map((option) => (
              <Radio key={option.value} value={option.value} colorScheme="teal">
                {option.label}
              </Radio>
            ))}
          </Stack>
        </RadioGroup>
      </FormControl>
      {isExisting && !fromUpload ? (
        <FormControl mb={4}>
          <FormLabel htmlFor="existing_repo">Your GitHub repos</FormLabel>
          <FilterableSelect
            id="existing_repo"
            options={repoOptions}
            isLoading={reposQuery.isPending || reposQuery.isFetching}
            placeholder="Start typing…"
            emptyMessage={
              serverSearch
                ? "No repo matches that on GitHub."
                : "No repo matches that."
            }
            value={repoSearch}
            onChange={setRepoSearch}
            onSelect={(fullName) => {
              setRepoSearch(fullName)
              selectRepo(fullName)
            }}
          />
          <FormHelperText>
            Not listed? Paste the URL below instead.
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
            Up to 50 MB. A new GitHub repo will be created with the contents as
            the first commit. Exclude large data files for now and add them with
            DVC afterwards.
          </FormHelperText>
        </FormControl>
      ) : null}
      {fromOverleaf ? (
        <FormControl
          isRequired
          isInvalid={!!errors.overleaf_project_url}
          mb={4}
        >
          <FormLabel htmlFor="overleaf_project_url">
            Overleaf project URL
          </FormLabel>
          <Input
            id="overleaf_project_url"
            {...register("overleaf_project_url", {
              required: "An Overleaf project URL is required.",
            })}
            placeholder="Ex: https://www.overleaf.com/project/abc123"
            autoComplete="off"
          />
          {errors.overleaf_project_url ? (
            <FormErrorMessage>
              {errors.overleaf_project_url.message}
            </FormErrorMessage>
          ) : null}
        </FormControl>
      ) : null}
      <FormControl isRequired={!fromOverleaf} isInvalid={!!errors.title} mb={4}>
        <FormLabel htmlFor="title">
          {fromOverleaf ? "Title (optional)" : "Title"}
        </FormLabel>
        <Input
          id="title"
          {...register("title", {
            required: fromOverleaf ? false : "Title is required.",
            // Passed through register so it chains with the form's own
            // handler rather than replacing it.
            onChange: isExisting ? undefined : onTitleChange,
          })}
          placeholder={
            fromOverleaf
              ? "Read from the Overleaf paper if left blank"
              : "Ex: Coherent structures in high Reynolds number boundary layers"
          }
          autoComplete="off"
          data-form-type="other"
          data-lpignore="true"
          data-1p-ignore="true"
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
          placeholder="One sentence describing what the project investigates."
          autoComplete="off"
        />
      </FormControl>
      {fromTemplate ? (
        <FormControl mb={4}>
          <FormLabel htmlFor="template">Template</FormLabel>
          <Select id="template" {...register("template")}>
            {TEMPLATES.map((template) => (
              <option key={template.value} value={template.value}>
                {template.label}
              </option>
            ))}
          </Select>
        </FormControl>
      ) : null}
      {fromTemplate ? (
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
      {isOrgRepo ? (
        <Box
          mb={4}
          p={4}
          borderRadius="md"
          borderWidth={1}
          borderColor={appInstalledForOrg ? "ui.success" : "orange.300"}
          fontSize="sm"
        >
          <Text fontWeight="semibold" mb={1}>
            This repo belongs to the organization {repoOwner}
          </Text>
          <Text color="ui.dim" mb={2}>
            Calkit will add {repoOwner} as an organization here, which needs you
            to be one of its admins on GitHub, and the Calkit GitHub App has to
            be installed for it so Calkit can work with its repos.
          </Text>
          {installationsQuery.isPending ? (
            <Text color="ui.dim">Checking the app installation…</Text>
          ) : appInstalledForOrg ? (
            <Flex align="center" gap={2} color="ui.success">
              <Icon as={CheckCircleIcon} />
              The Calkit App is installed for {repoOwner}.
            </Flex>
          ) : (
            <HStack spacing={3}>
              <Button
                as={Link}
                size="sm"
                variant="primary"
                href={`https://github.com/apps/${appName}/installations/new`}
                isExternal
              >
                Install the Calkit App for {repoOwner}{" "}
                <ExternalLinkIcon ml={1} />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => installationsQuery.refetch()}
                isLoading={installationsQuery.isFetching}
              >
                Check again
              </Button>
            </HStack>
          )}
        </Box>
      ) : null}
      {!isExisting ? (
        <FormControl mb={6}>
          <Checkbox {...register("is_public")} colorScheme="teal">
            Make it public
          </Checkbox>
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

/**
 * The new project form, as a modal over whatever page you're on.
 *
 * A modal rather than a page so starting a project doesn't take the current
 * page away and put it back.
 */
const NewProjectModal = ({
  isOpen,
  onClose,
  initialPath,
  defaultTemplate,
  onCreated,
}: {
  isOpen: boolean
  onClose: () => void
  initialPath?: StartPath
  defaultTemplate?: string
  onCreated?: (project: ProjectPublic) => void
}) => {
  const navigate = useNavigate()
  const created = (project: ProjectPublic) => {
    onClose()
    if (onCreated) {
      onCreated(project)
      return
    }
    navigate({
      to: "/$accountName/$projectName",
      params: {
        accountName: project.owner_account_name,
        projectName: project.name,
      },
    })
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size="2xl"
      scrollBehavior="inside"
      isCentered
      motionPreset="none"
    >
      <ModalOverlay />
      <ModalContent>
        <ModalCloseButton />
        <ModalBody px={{ base: 6, md: 10 }} py={8}>
          <NewProjectForm
            initialPath={initialPath}
            defaultTemplate={defaultTemplate}
            onCreated={created}
          />
        </ModalBody>
      </ModalContent>
    </Modal>
  )
}

export default NewProjectModal
