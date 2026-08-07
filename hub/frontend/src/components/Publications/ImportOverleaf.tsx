import {
  Button,
  Checkbox,
  Flex,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Textarea,
  Switch,
  HStack,
  Text,
  IconButton,
  Collapse,
  Box,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { type SubmitHandler, useForm } from "react-hook-form"
import { getRouteApi } from "@tanstack/react-router"
import { useState } from "react"
import {
  DownloadIcon,
  ChevronDownIcon,
  ChevronRightIcon,
} from "@chakra-ui/icons"

import { ProjectsService, UsersService } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface ImportOverleafProps {
  isOpen: boolean
  onClose: () => void
}

interface OverleafImportPost {
  path: string
  title?: string | null
  description?: string | null
  kind:
    | "journal-article"
    | "conference-paper"
    | "masters-thesis"
    | "phd-thesis"
    | "report"
    | "book"
    | "other"
  overleaf_url: string
  stage?: string | null
  environment?: string | null
  overleaf_token?: string | null
  target_path?: string | null
  auto_build: boolean
  file?: FileList
}

const ImportOverleaf = ({ isOpen, onClose }: ImportOverleafProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const connectedAccountsQuery = useQuery({
    queryFn: () => UsersService.getUserConnectedAccounts(),
    queryKey: ["user", "connected-accounts"],
  })
  const [importZip, setImportZip] = useState(false)
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<OverleafImportPost>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      path: "paper",
      title: null,
      description: null,
      kind: "journal-article",
      overleaf_url: "",
      stage: null,
      environment: null,
      overleaf_token: null,
      target_path: null,
      auto_build: false,
    },
  })
  const [showAdvanced, setShowAdvanced] = useState(false)
  const mutation = useMutation({
    mutationFn: (data: OverleafImportPost) =>
      ProjectsService.postProjectOverleafPublication({
        formData: {
          path: data.path,
          overleaf_project_url: data.overleaf_url,
          kind: data.kind,
          auto_build: data.auto_build,
          title: data.title || undefined,
          description: data.description || undefined,
          target_path: data.target_path || undefined,
          stage_name: data.stage || undefined,
          environment_name: data.environment || undefined,
          overleaf_token: data.overleaf_token || undefined,
          file: data.file ? data.file[0] : null,
        },
        ownerName: accountName,
        projectName: projectName,
      }),
    onSuccess: (_pub, vars) => {
      showToast(
        "Success!",
        vars.file ? "Overleaf ZIP imported." : "Overleaf project linked.",
        "success",
      )
      reset()
      setImportZip(false)
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "publications"],
      })
    },
  })
  const onSubmit: SubmitHandler<OverleafImportPost> = (data) => {
    mutation.mutate(data)
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
        <ModalContent
          as="form"
          name="overleaf-import"
          autoComplete="off"
          onSubmit={handleSubmit(onSubmit)}
        >
          <ModalHeader>Import from Overleaf</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <FormControl mb={4}>
              <HStack>
                <Text fontSize="sm" color={importZip ? "gray.500" : undefined}>
                  Import/link
                </Text>
                <Switch
                  isChecked={importZip}
                  onChange={(e) => setImportZip(e.target.checked)}
                  colorScheme="teal"
                  aria-label="Toggle ZIP import"
                />
                <Text fontSize="sm" color={!importZip ? "gray.500" : undefined}>
                  Import ZIP
                </Text>
              </HStack>
            </FormControl>
            {/* Overleaf URL field, required only if not importing ZIP */}
            <FormControl
              isRequired={!importZip}
              isInvalid={!!errors.overleaf_url}
            >
              <FormLabel htmlFor="overleaf_url">Overleaf project URL</FormLabel>
              <HStack>
                <Input
                  id="overleaf_url"
                  {...register("overleaf_url", {
                    validate: (value) => {
                      // Skip validation if in ZIP import mode
                      if (watch("file")?.length) return true
                      // Otherwise require non-empty URL
                      return (
                        value.trim() !== "" ||
                        "Overleaf project URL is required"
                      )
                    },
                  })}
                  placeholder={"Ex: https://www.overleaf.com/project/abc123..."}
                  type="text"
                />
                {/* Show download button if in ZIP mode and URL has a value */}
                {importZip &&
                  (() => {
                    const overleafUrl = watch("overleaf_url")
                    return overleafUrl && overleafUrl.trim() !== "" ? (
                      <IconButton
                        as="a"
                        href={overleafUrl + "/download/zip"}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label="Download ZIP from Overleaf"
                        icon={<DownloadIcon />}
                        title="Download ZIP from Overleaf"
                        variant="outline"
                        size="md"
                      />
                    ) : null
                  })()}
              </HStack>
              {errors.overleaf_url && (
                <FormErrorMessage>
                  {errors.overleaf_url.message}
                </FormErrorMessage>
              )}
            </FormControl>
            {importZip ? (
              <FormControl mt={4} isRequired>
                <FormLabel htmlFor="zip_file">Overleaf ZIP file</FormLabel>
                <Input
                  pt={1}
                  id="zip_file"
                  {...register("file", {
                    required: importZip ? "ZIP file is required" : false,
                  })}
                  type="file"
                  accept=".zip"
                />
              </FormControl>
            ) : !connectedAccountsQuery.data?.overleaf ? (
              <FormControl
                mt={4}
                isRequired
                isInvalid={!!errors.overleaf_token}
              >
                <FormLabel htmlFor="overleaf_token">Overleaf token</FormLabel>
                <Input
                  id="overleaf_token"
                  {...register("overleaf_token", {
                    validate: (value) => {
                      // Skip validation if in ZIP import mode
                      if (watch("file")?.length) return true
                      return (
                        (value && value.trim() !== "") ||
                        "Overleaf token is required"
                      )
                    },
                  })}
                  placeholder={"Ex: olp_..."}
                  type="text"
                />
                {errors.overleaf_token && (
                  <FormErrorMessage>
                    {errors.overleaf_token.message}
                  </FormErrorMessage>
                )}
              </FormControl>
            ) : null}
            {/* Destination folder */}
            <FormControl mt={4} isRequired isInvalid={!!errors.path}>
              <FormLabel htmlFor="path">Destination folder</FormLabel>
              <Input
                id="path"
                {...register("path", {
                  required: "Path is required",
                  validate: (value) =>
                    value.trim() !== "" || "Path is required",
                })}
                placeholder={"Ex: paper"}
                type="text"
              />
              {errors.path && (
                <FormErrorMessage>{errors.path.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Publication type */}
            <FormControl mt={4} isRequired isInvalid={!!errors.kind}>
              <FormLabel htmlFor="kind">Type</FormLabel>
              <Select
                id="kind"
                {...register("kind", {
                  required: "Type is required",
                })}
              >
                <option value="journal-article">Journal article</option>
                <option value="conference-paper">Conference paper</option>
                <option value="report">Report</option>
                <option value="book">Book</option>
                <option value="masters-thesis">Master's thesis</option>
                <option value="phd-thesis">PhD thesis</option>
                <option value="other">Other</option>
              </Select>
            </FormControl>
            {/* Title */}
            <FormControl mt={4} isInvalid={!!errors.title}>
              <FormLabel htmlFor="title">Title</FormLabel>
              <Input
                id="title"
                {...register("title")}
                placeholder="Title"
                type="text"
                autoComplete="off"
              />
              {errors.title && (
                <FormErrorMessage>{errors.title.message}</FormErrorMessage>
              )}
            </FormControl>
            {/* Description */}
            <FormControl mt={4} isInvalid={!!errors.description}>
              <FormLabel htmlFor="description">Description</FormLabel>
              <Textarea
                id="description"
                {...register("description")}
                placeholder="Description"
              />
              {errors.description && (
                <FormErrorMessage>
                  {errors.description.message}
                </FormErrorMessage>
              )}
            </FormControl>
            {/* Auto-build */}
            <Flex mt={4}>
              <FormControl>
                <Checkbox
                  {...register("auto_build")}
                  colorScheme="teal"
                  id="auto_build"
                >
                  Build PDF automatically when updated
                </Checkbox>
              </FormControl>
            </Flex>
            {/* Advanced section toggle */}
            <Box mt={3}>
              <Button
                pl={0}
                pr={2}
                variant="ghost"
                size="md"
                onClick={() => setShowAdvanced(!showAdvanced)}
                leftIcon={
                  showAdvanced ? <ChevronDownIcon /> : <ChevronRightIcon />
                }
                fontWeight="normal"
              >
                Advanced
              </Button>
            </Box>
            {/* Advanced collapsible section */}
            <Collapse in={showAdvanced} animateOpacity>
              <Box pl={2} borderLeft="2px" borderColor="gray.200">
                {/* Target TeX file path */}
                <FormControl mt={4} isInvalid={!!errors.target_path}>
                  <FormLabel htmlFor="target_path">
                    Target TeX file path
                  </FormLabel>
                  <Input
                    id="target_path"
                    {...register("target_path")}
                    placeholder={"Ex: main.tex"}
                    type="text"
                  />
                  {errors.target_path && (
                    <FormErrorMessage>
                      {errors.target_path.message}
                    </FormErrorMessage>
                  )}
                </FormControl>
                {/* Environment name */}
                <FormControl mt={4} isInvalid={!!errors.environment}>
                  <FormLabel htmlFor="environment">
                    Docker environment name
                  </FormLabel>
                  <Input
                    id="environment"
                    {...register("environment")}
                    placeholder="Ex: tex"
                    type="text"
                  />
                  {errors.environment && (
                    <FormErrorMessage>
                      {errors.environment.message}
                    </FormErrorMessage>
                  )}
                </FormControl>
                {/* Stage name */}
                <FormControl mt={4} isInvalid={!!errors.stage}>
                  <FormLabel htmlFor="stage">Pipeline stage name</FormLabel>
                  <Input
                    id="stage"
                    {...register("stage")}
                    placeholder="Ex: build-paper"
                    type="text"
                  />
                  {errors.stage && (
                    <FormErrorMessage>{errors.stage.message}</FormErrorMessage>
                  )}
                </FormControl>
              </Box>
            </Collapse>
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
    </>
  )
}

export default ImportOverleaf
