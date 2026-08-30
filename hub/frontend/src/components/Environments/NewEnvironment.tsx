import { CloseIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Flex,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  HStack,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  SimpleGrid,
  Tag,
  TagLabel,
  Text,
  Textarea,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useParams } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import mixpanel from "mixpanel-browser"
import { useState } from "react"

import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import {
  ENV_KINDS,
  type EnvKind,
  PACKAGE_GROUPS,
  PRESETS,
  buildEnvironment,
  builtImageTagFor,
  defaultPathFor,
} from "../../lib/environments"
import { handleError } from "../../lib/errors"

interface NewEnvironmentProps {
  isOpen: boolean
  onClose: () => void
  /** Supplied when rendered outside the project route. */
  ownerName?: string
  projectName?: string
  onCreated?: (name: string) => void
}

/**
 * Create a computational environment without writing calkit.yaml by hand.
 *
 * Presets come first, because most projects want one of a handful of
 * well-trodden setups and picking "PyData" beats knowing that uv wants a
 * pyproject.toml with a dependencies array under [project]. Everything a
 * preset fills in stays editable, so it's a starting point, not a black box.
 */
const NewEnvironment = ({
  isOpen,
  onClose,
  ownerName,
  projectName: projectNameProp,
  onCreated,
}: NewEnvironmentProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeParams = useParams({ strict: false }) as {
    accountName?: string
    projectName?: string
  }
  const accountName = ownerName ?? routeParams.accountName ?? ""
  const projectName = projectNameProp ?? routeParams.projectName ?? ""
  const tagBg = useColorModeValue("gray.100", "gray.600")
  const [name, setName] = useState("")
  const [kind, setKind] = useState<EnvKind>("uv")
  const [description, setDescription] = useState("")
  const [packages, setPackages] = useState<string[]>([])
  const [newPackage, setNewPackage] = useState("")
  const [image, setImage] = useState("")
  const [pythonVersion, setPythonVersion] = useState("3.13")
  const [pathOverride, setPathOverride] = useState("")
  const [nameTouched, setNameTouched] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [usedPreset, setUsedPreset] = useState<string | null>(null)
  const spec = ENV_KINDS.find((k) => k.kind === kind) ?? ENV_KINDS[0]
  const path = pathOverride || defaultPathFor(kind, name || "py")
  const applyPreset = (presetName: string) => {
    const preset = PRESETS.find((p) => p.name === presetName)
    if (!preset) return
    // Whether presets carry the load, or people configure from scratch.
    mixpanel.track("Applied environment preset", {
      preset: preset.name,
      kind: preset.kind,
    })
    setUsedPreset(preset.name)
    setKind(preset.kind)
    setPackages(preset.packages ?? [])
    setImage(preset.image ?? "")
    setPathOverride("")
    // A name the user typed is theirs; only fill in one they haven't.
    if (!nameTouched) {
      setName(preset.envName)
    }
  }
  const addPackage = (value: string) => {
    const trimmed = value.trim()
    if (!trimmed) return
    setPackages((current) =>
      current.includes(trimmed) ? current : [...current, trimmed],
    )
    setNewPackage("")
  }
  const addGroup = (groupName: string) => {
    const group = PACKAGE_GROUPS[groupName] ?? []
    setPackages((current) => [
      ...current,
      ...group.filter((pkg) => !current.includes(pkg)),
    ])
  }
  const nameError = submitted && !name ? "A name is required." : undefined
  const imageError =
    submitted && spec.needsImage && !image ? "An image is required." : undefined
  // A Docker environment with nothing to install is just the image, so
  // there's no Dockerfile to show a path for.
  const imageOnly = kind === "docker" && packages.length === 0
  // The modal stays mounted between openings, so what was typed would
  // otherwise greet the next "New environment" click.
  const resetForm = () => {
    setName("")
    setKind("uv")
    setDescription("")
    setPackages([])
    setNewPackage("")
    setImage("")
    setPythonVersion("3.13")
    setPathOverride("")
    setNameTouched(false)
    setSubmitted(false)
    setUsedPreset(null)
  }
  const close = () => {
    resetForm()
    onClose()
  }
  const mutation = useMutation({
    mutationFn: () =>
      ProjectsService.postProjectEnvironment({
        owner_name: accountName,
        project_name: projectName,
        environment: buildEnvironment({
          name,
          kind,
          path,
          description,
          packages,
          image,
          pythonVersion,
        }),
      }).then((response) => response.data),
    onSuccess: () => {
      mixpanel.track("Created environment", {
        kind,
        preset: usedPreset,
        n_packages: packages.length,
      })
      showToast("Success!", "Environment created.", "success")
      close()
      onCreated?.(name)
    },
    onError: (err: AxiosError) => handleError(err, showToast),
    onSettled: () =>
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "environments"],
      }),
  })
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (!name || (spec.needsImage && !image)) return
    mutation.mutate()
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={close}
      size={{ base: "sm", md: "2xl" }}
      isCentered
      scrollBehavior="inside"
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={submit}>
        <ModalHeader>New environment</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl mb={5}>
            <FormLabel>Start from</FormLabel>
            <SimpleGrid columns={{ base: 1, md: 2 }} spacing={2}>
              {PRESETS.map((preset) => (
                <Button
                  key={preset.name}
                  size="sm"
                  variant="outline"
                  justifyContent="flex-start"
                  fontWeight="normal"
                  onClick={() => applyPreset(preset.name)}
                >
                  {preset.label}
                </Button>
              ))}
            </SimpleGrid>
            <FormHelperText>
              Fills in the fields below, all of which stay editable.
            </FormHelperText>
          </FormControl>
          <FormControl isRequired isInvalid={Boolean(nameError)} mb={4}>
            <FormLabel htmlFor="env-name">Name</FormLabel>
            <Input
              id="env-name"
              // A short field named "name" is what password managers latch
              // onto; these turn off Dashlane, 1Password, LastPass, and the
              // browser's own suggestions, which otherwise cover the field.
              name="calkit-environment-name"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setNameTouched(true)
              }}
              placeholder="Ex: py"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              data-1p-ignore="true"
            />
            {nameError ? (
              <FormErrorMessage>{nameError}</FormErrorMessage>
            ) : (
              <FormHelperText>How pipeline stages refer to it.</FormHelperText>
            )}
          </FormControl>
          <FormControl mb={4}>
            <FormLabel htmlFor="env-kind">Kind</FormLabel>
            <Select
              id="env-kind"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as EnvKind)
                setPathOverride("")
              }}
            >
              {ENV_KINDS.map((option) => (
                <option key={option.kind} value={option.kind}>
                  {option.label}
                </option>
              ))}
            </Select>
            <FormHelperText>{spec.hint}</FormHelperText>
          </FormControl>
          {spec.needsImage ? (
            <FormControl isRequired isInvalid={Boolean(imageError)} mb={4}>
              <FormLabel htmlFor="env-image">Docker image</FormLabel>
              <Input
                id="env-image"
                value={image}
                onChange={(e) => setImage(e.target.value)}
                placeholder="Ex: python:3.13-slim"
                autoComplete="off"
              />
              {imageError ? (
                <FormErrorMessage>{imageError}</FormErrorMessage>
              ) : (
                <FormHelperText>
                  {imageOnly
                    ? "Pulled and used as is. Add packages below to build " +
                      "on top of it instead."
                    : `The base image. Packages are installed on top of it and the result is tagged ${builtImageTagFor(
                        name || "env",
                      )}, so the base is left as it was.`}
                </FormHelperText>
              )}
            </FormControl>
          ) : null}
          {spec.pythonVersion ? (
            <FormControl mb={4}>
              <FormLabel htmlFor="env-python">Python version</FormLabel>
              <Input
                id="env-python"
                value={pythonVersion}
                onChange={(e) => setPythonVersion(e.target.value)}
                placeholder="3.13"
                width="120px"
                autoComplete="off"
              />
            </FormControl>
          ) : null}
          {spec.packageLabel ? (
            <FormControl mb={4}>
              <FormLabel>{spec.packageLabel}</FormLabel>
              {packages.length ? (
                <Flex wrap="wrap" gap={2} mb={2}>
                  {packages.map((pkg) => (
                    <Tag key={pkg} bg={tagBg} borderRadius="full">
                      <TagLabel>{pkg}</TagLabel>
                      <Box
                        as="button"
                        type="button"
                        aria-label={`Remove ${pkg}`}
                        ml={2}
                        fontSize="8px"
                        onClick={() =>
                          setPackages((current) =>
                            current.filter((p) => p !== pkg),
                          )
                        }
                      >
                        <CloseIcon />
                      </Box>
                    </Tag>
                  ))}
                </Flex>
              ) : null}
              <HStack>
                <Input
                  value={newPackage}
                  onChange={(e) => setNewPackage(e.target.value)}
                  onKeyDown={(e) => {
                    // Enter adds a package rather than submitting the form,
                    // which is what typing a list of them expects.
                    if (e.key === "Enter") {
                      e.preventDefault()
                      addPackage(newPackage)
                    }
                  }}
                  placeholder={spec.packagePlaceholder}
                  autoComplete="off"
                />
                <Button
                  size="sm"
                  onClick={() => addPackage(newPackage)}
                  isDisabled={!newPackage.trim()}
                >
                  Add
                </Button>
              </HStack>
              {spec.packageGroups?.length ? (
                <Flex wrap="wrap" gap={2} mt={2}>
                  {spec.packageGroups.map((groupName) => (
                    <Button
                      key={groupName}
                      size="xs"
                      variant="ghost"
                      onClick={() => addGroup(groupName)}
                      title={PACKAGE_GROUPS[groupName]?.join(", ")}
                    >
                      + {groupName}
                    </Button>
                  ))}
                </Flex>
              ) : null}
            </FormControl>
          ) : null}
          {imageOnly ? null : (
            <FormControl mb={4}>
              <FormLabel htmlFor="env-path">Spec file</FormLabel>
              <Input
                id="env-path"
                value={path}
                onChange={(e) => setPathOverride(e.target.value)}
                autoComplete="off"
              />
              <FormHelperText>
                Lives in your repo, so the environment travels with the project.
              </FormHelperText>
            </FormControl>
          )}
          <FormControl>
            <FormLabel htmlFor="env-description">Description</FormLabel>
            <Textarea
              id="env-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What this environment is for"
              rows={2}
            />
          </FormControl>
          <Text fontSize="xs" color="ui.dim" mt={4}>
            Exact versions get pinned to a lock file the first time it runs,
            which is what makes it reproducible for everyone else.
          </Text>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={mutation.isPending}
          >
            Create
          </Button>
          <Button onClick={close}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default NewEnvironment
