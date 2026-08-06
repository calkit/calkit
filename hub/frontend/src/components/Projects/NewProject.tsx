import {
  Button,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  Flex,
  Checkbox,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Link,
  useDisclosure,
  Switch,
} from "@chakra-ui/react"
import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import mixpanel from "mixpanel-browser"
import { useNavigate } from "@tanstack/react-router"

import {
  type ApiError,
  ProjectsService,
  type ProjectPost,
  type UserPublic,
  type ProjectPublic,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { appName } from "../../lib/core"

interface NewProjectProps {
  isOpen: boolean
  onClose: () => void
  defaultTemplate?: string
}

const NewProject = ({ isOpen, onClose, defaultTemplate }: NewProjectProps) => {
  const [repoExists, setRepoExists] = useState(false)
  const templates = [
    "calkit/example-basic",
    "calkit/example-matlab",
    "calkit/example-analytics",
  ]
  if (!defaultTemplate) {
    defaultTemplate = "calkit/example-basic"
  }
  if (!templates.includes(defaultTemplate)) {
    templates.push(defaultTemplate)
  }
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const navigate = useNavigate()
  const errorModal = useDisclosure()
  const currentUser = queryClient.getQueryData<UserPublic>(["currentUser"])
  const githubUsername = currentUser?.github_username
    ? currentUser.github_username
    : "your-name"
  const {
    register,
    handleSubmit,
    reset,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<ProjectPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      title: "",
      name: "",
      description: "",
      git_repo_url: `https://github.com/${githubUsername}/`,
      is_public: false,
      template: defaultTemplate,
      git_repo_exists: false,
    },
  })
  const mutation = useMutation({
    mutationFn: (data: ProjectPost) => {
      if (data.template === "") {
        data.template = null
      }
      // Ensure project name is consistent with Git repo URL
      const gitName = String(data.git_repo_url).split("/").at(-1)
      if (gitName) {
        data.name = gitName.toLowerCase()
      }
      data.git_repo_exists = repoExists
      if (repoExists) {
        data.template = null
      }
      return ProjectsService.postProject({ requestBody: data })
    },
    onSuccess: (data: ProjectPublic) => {
      mixpanel.track("Created new project")
      showToast("Success!", "Project created successfully.", "success")
      const accountName = data.owner_account_name
      const projectName = data.name
      reset()
      onClose()
      // Invalidate queries for user projects
      queryClient.invalidateQueries({ queryKey: ["projects"] })
      // Navigate to the new project's page
      navigate({
        to: "/$accountName/$projectName",
        params: { accountName, projectName },
      })
    },
    onError: (err: ApiError) => {
      // If the error indicates that the Calkit GitHub App is not enabled,
      // show an error modal with the link to install it
      const msg = (err?.message || "").toLowerCase()
      const bodyDetail =
        typeof (err as any)?.body?.detail === "string"
          ? ((err as any).body.detail as string).toLowerCase()
          : ""
      if (
        msg.includes("calkit github app not enabled") ||
        bodyDetail.includes("calkit github app not enabled")
      ) {
        errorModal.onOpen()
        return
      }
      handleError(err, showToast)
    },
  })
  const onSubmit: SubmitHandler<ProjectPost> = (data) => {
    mutation.mutate(data)
  }
  const onTitleChange = (e: any) => {
    if (repoExists) return
    const projectName = String(e.target.value)
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^\w-]+/g, "")
    const repoUrl = `https://github.com/${githubUsername}/${projectName}`
    setValue("git_repo_url", repoUrl)
    setValue("name", projectName)
  }
  const onGitRepoUrlChange = (e: any) => {
    const value = String(e.target.value)
    if (!repoExists) return
    try {
      // Extract repo name from URL and generate a human title
      const parts = value.split("/").filter(Boolean)
      if (parts.length < 4) return
      const last = parts.at(-1) || ""
      const repoName = last.replace(/\.git$/i, "")
      const spaced = repoName.replace(/[-_]+/g, " ").trim()
      const title = spaced
        ? spaced.charAt(0).toUpperCase() + spaced.slice(1)
        : ""
      if (title) setValue("title", title)
      if (repoName) setValue("name", repoName.toLowerCase())
    } catch (_) {
      // Ignore parsing errors
    }
  }

  return (
    <>
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        size={{ base: "sm", md: "md" }}
        isCentered
      >
        <ModalOverlay />
        <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
          <ModalHeader>New project</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl display="flex" alignItems="center" mb={4}>
              <FormLabel htmlFor="repo-exists" mb="0">
                GitHub repo exists?
              </FormLabel>
              <Switch
                id="repo-exists"
                isChecked={repoExists}
                onChange={(e) => setRepoExists(e.target.checked)}
                colorScheme="teal"
              />
            </FormControl>
            <FormControl isRequired isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
                id="title"
                {...register("title", {
                  required: "Title is required.",
                })}
                placeholder="Ex: Coherent structures in high Reynolds number boundary layers"
                type="text"
                onChange={!repoExists ? onTitleChange : undefined}
                autoComplete="off"
              />
              {errors.title && (
                <FormErrorMessage>{errors.title.message}</FormErrorMessage>
              )}
            </FormControl>
            <FormControl mt={4}>
              <FormLabel htmlFor="description">Description</FormLabel>
              <Input
                id="description"
                {...register("description")}
                placeholder="Description"
                type="text"
                autoComplete="off"
              />
            </FormControl>
            {!repoExists && (
              <FormControl mt={4}>
                <FormLabel htmlFor="template">Template</FormLabel>
                <Select
                  id="template"
                  placeholder="Select a template..."
                  {...register("template", {})}
                  defaultValue={defaultTemplate}
                >
                  {templates.map((template) => (
                    <option key={template} value={template}>
                      {template}
                    </option>
                  ))}
                  <option key="none" value="">
                    None
                  </option>
                </Select>
              </FormControl>
            )}
            <FormControl mt={4} isInvalid={!!errors.git_repo_url}>
              <FormLabel htmlFor="git_repo_url">GitHub repo URL</FormLabel>
              <Input
                id="git_repo_url"
                {...register("git_repo_url", {
                  required: "GitHub repo URL is required.",
                  onChange: onGitRepoUrlChange,
                })}
                placeholder="Ex: https://github.com/your_name/your_repo"
                type="text"
                autoComplete="off"
              />
              {errors.git_repo_url && (
                <FormErrorMessage>
                  {errors.git_repo_url.message}
                </FormErrorMessage>
              )}
            </FormControl>
            {!repoExists && (
              <Flex mt={4}>
                <FormControl>
                  <Checkbox {...register("is_public")} colorScheme="teal">
                    Public?
                  </Checkbox>
                </FormControl>
              </Flex>
            )}
          </ModalBody>
          <ModalFooter gap={3}>
            <Button
              variant="primary"
              type="submit"
              isLoading={isSubmitting || mutation.isPending}
            >
              Save
            </Button>
            <Button onClick={onClose}>Cancel</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      {/* Error modal prompting user to install the GitHub App */}
      <Modal isOpen={errorModal.isOpen} onClose={errorModal.onClose} isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>GitHub app not enabled</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            To create a project, the Calkit GitHub App must be installed for
            your account or organization and have access to any relevant repos.
            Install it on GitHub, then return here and try again.
          </ModalBody>
          <ModalFooter gap={3}>
            <Link
              href={`https://github.com/apps/${appName}/installations/new`}
              isExternal
            >
              <Button variant="primary">Install on GitHub</Button>
            </Link>
            <Button onClick={errorModal.onClose}>Close</Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </>
  )
}

export default NewProject
