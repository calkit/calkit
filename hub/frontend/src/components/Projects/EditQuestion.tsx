import {
  Box,
  Button,
  Flex,
  FormControl,
  FormErrorMessage,
  FormLabel,
  IconButton,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Text,
  Textarea,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { getRouteApi } from "@tanstack/react-router"
import { useEffect } from "react"
import { type SubmitHandler, useFieldArray, useForm } from "react-hook-form"
import { FaPlus, FaTrash } from "react-icons/fa"

import { ProjectsService, type QuestionPublic } from "../../client"
import type { ApiError } from "../../client/core/ApiError"
import useCustomToast from "../../hooks/useCustomToast"
import {
  useProjectFigures,
  useProjectPublications,
  useProjectResults,
} from "../../hooks/useProject"
import { handleError } from "../../lib/errors"
import { submitOnCmdEnter } from "../../lib/keyboard"

interface EditQuestionProps {
  question: QuestionPublic | null
  isOpen: boolean
  onClose: () => void
  // Git ref currently being browsed, so figure/result options come from the
  // same snapshot the question does.
  gitRef?: string
}

interface EvidenceRow {
  // Combined "kind:path" so a single dropdown can pick figure or result.
  selection: string
  key: string
  explanation: string
}

interface EditQuestionForm {
  question: string
  hypothesis: string
  answer: string
  evidence: EvidenceRow[]
}

const rowToSelection = (kind: string, path: string) => `${kind}:${path}`

const parseSelection = (selection: string) => {
  const idx = selection.indexOf(":")
  if (idx < 0) {
    return null
  }
  return {
    kind: selection.slice(0, idx) as "figure" | "result" | "publication",
    path: selection.slice(idx + 1),
  }
}

const EditQuestion = ({
  question,
  isOpen,
  onClose,
  gitRef,
}: EditQuestionProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const routeApi = getRouteApi("/_layout/$accountName/$projectName")
  const { accountName, projectName } = routeApi.useParams()
  const { figuresRequest } = useProjectFigures(accountName, projectName, gitRef)
  const { resultsRequest } = useProjectResults(accountName, projectName, gitRef)
  const { publicationsRequest } = useProjectPublications(
    accountName,
    projectName,
    gitRef,
  )
  const {
    register,
    control,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<EditQuestionForm>({
    mode: "onBlur",
    defaultValues: { question: "", hypothesis: "", answer: "", evidence: [] },
  })
  const { fields, append, remove } = useFieldArray({
    control,
    name: "evidence",
  })
  // Prefill from the selected question whenever it changes.
  useEffect(() => {
    if (!question) {
      return
    }
    reset({
      question: question.question,
      hypothesis: question.hypothesis ?? "",
      answer: question.answer ?? "",
      evidence: (question.evidence ?? []).map((ev) => ({
        selection: rowToSelection(ev.kind, ev.path),
        key: ev.key ?? "",
        explanation: ev.explanation ?? "",
      })),
    })
  }, [question, reset])
  const mutation = useMutation({
    mutationFn: (data: EditQuestionForm) =>
      ProjectsService.putProjectQuestion({
        ownerName: accountName,
        projectName: projectName,
        number: Number(question?.number),
        requestBody: {
          question: data.question,
          hypothesis: data.hypothesis,
          answer: data.answer,
          evidence: data.evidence.flatMap((row) => {
            const parsed = parseSelection(row.selection)
            if (!parsed) {
              return []
            }
            return [
              {
                kind: parsed.kind,
                path: parsed.path,
                key: parsed.kind === "result" && row.key ? row.key : undefined,
                explanation: row.explanation ? row.explanation : undefined,
              },
            ]
          }),
        },
      }),
    onSuccess: () => {
      showToast("Success!", "Question updated.", "success")
      onClose()
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["projects", accountName, projectName, "questions"],
      })
    },
  })
  const onSubmit: SubmitHandler<EditQuestionForm> = (data) => {
    if (!question) {
      return
    }
    mutation.mutate(data)
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      size={{ base: "sm", md: "lg" }}
      isCentered
    >
      <ModalOverlay />
      <ModalContent
        as="form"
        onSubmit={handleSubmit(onSubmit)}
        onKeyDown={submitOnCmdEnter(handleSubmit(onSubmit))}
      >
        <ModalHeader>Edit question</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl isRequired isInvalid={!!errors.question} mb={4}>
            <FormLabel htmlFor="question">Question</FormLabel>
            <Textarea
              id="question"
              {...register("question", { required: "Question is required" })}
            />
            {errors.question ? (
              <FormErrorMessage>{errors.question.message}</FormErrorMessage>
            ) : null}
          </FormControl>
          <FormControl mb={4}>
            <FormLabel htmlFor="hypothesis">Hypothesis</FormLabel>
            <Textarea
              id="hypothesis"
              {...register("hypothesis")}
              placeholder="What you expect the answer to be"
            />
          </FormControl>
          <FormControl mb={4}>
            <FormLabel htmlFor="answer">Answer</FormLabel>
            <Textarea
              id="answer"
              {...register("answer")}
              placeholder="What the project found"
            />
          </FormControl>
          <FormControl>
            <Flex align="center" mb={2}>
              <FormLabel mb={0}>Evidence</FormLabel>
              <IconButton
                aria-label="Add evidence"
                icon={<FaPlus />}
                size="xs"
                ml={-1.5}
                onClick={() =>
                  append({ selection: "", key: "", explanation: "" })
                }
              />
            </Flex>
            {fields.length === 0 ? (
              <Text fontSize="sm" color="gray.500">
                No evidence linked yet.
              </Text>
            ) : null}
            {fields.map((field, index) => {
              const selection = watch(`evidence.${index}.selection`) || ""
              const parsed = parseSelection(selection)
              const figures = figuresRequest.data ?? []
              const results = resultsRequest.data ?? []
              const publications = publicationsRequest.data ?? []
              // Always keep the current selection as an available option, even
              // if it isn't in the fetched lists (still loading, or the file
              // was renamed/removed), so the dropdown never blanks out.
              const selectionInList =
                (parsed?.kind === "figure" &&
                  figures.some((f) => f.path === parsed.path)) ||
                (parsed?.kind === "result" &&
                  results.some((r) => r.path === parsed.path)) ||
                (parsed?.kind === "publication" &&
                  publications.some((p) => p.path === parsed.path))
              return (
                <Box
                  key={field.id}
                  borderWidth={1}
                  borderRadius="md"
                  p={3}
                  mb={2}
                >
                  <Flex justify="flex-end">
                    <IconButton
                      aria-label="Remove evidence"
                      icon={<FaTrash />}
                      size="xs"
                      variant="ghost"
                      onClick={() => remove(index)}
                    />
                  </Flex>
                  <FormControl mb={2}>
                    <FormLabel fontSize="xs" mb={1}>
                      Figure, result, or publication
                    </FormLabel>
                    <Select
                      {...register(`evidence.${index}.selection`)}
                      value={selection}
                      placeholder="Select a figure, result, or publication"
                      size="sm"
                    >
                      {parsed && !selectionInList ? (
                        <option value={selection}>{parsed.path}</option>
                      ) : null}
                      {figures.length > 0 ? (
                        <optgroup label="Figures">
                          {figures.map((fig) => (
                            <option
                              key={`figure:${fig.path}`}
                              value={rowToSelection("figure", fig.path)}
                            >
                              {fig.path}
                            </option>
                          ))}
                        </optgroup>
                      ) : null}
                      {results.length > 0 ? (
                        <optgroup label="Results">
                          {results.map((res) => (
                            <option
                              key={`result:${res.path}`}
                              value={rowToSelection("result", res.path)}
                            >
                              {res.path}
                            </option>
                          ))}
                        </optgroup>
                      ) : null}
                      {publications.length > 0 ? (
                        <optgroup label="Publications">
                          {publications.map((pub) => (
                            <option
                              key={`publication:${pub.path}`}
                              value={rowToSelection("publication", pub.path)}
                            >
                              {pub.path}
                            </option>
                          ))}
                        </optgroup>
                      ) : null}
                    </Select>
                  </FormControl>
                  {parsed?.kind === "result" ? (
                    <FormControl mb={2}>
                      <FormLabel fontSize="xs" mb={1}>
                        Key (optional)
                      </FormLabel>
                      <Input
                        {...register(`evidence.${index}.key`)}
                        placeholder="e.g. mean"
                        size="sm"
                      />
                    </FormControl>
                  ) : null}
                  <FormControl>
                    <FormLabel fontSize="xs" mb={1}>
                      Explanation (optional)
                    </FormLabel>
                    <Input
                      {...register(`evidence.${index}.explanation`)}
                      placeholder="How this supports the answer"
                      size="sm"
                    />
                  </FormControl>
                </Box>
              )
            })}
          </FormControl>
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
  )
}

export default EditQuestion
