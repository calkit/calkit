import { ExternalLinkIcon } from "@chakra-ui/icons"
import {
  Button,
  Divider,
  FormControl,
  FormErrorMessage,
  FormLabel,
  HStack,
  Link,
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
import { useMutation } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { type SubmitHandler, useForm } from "react-hook-form"

import { MiscService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { submitOnCmdEnter } from "../../lib/keyboard"

interface HelpFeedbackProps {
  isOpen: boolean
  onClose: () => void
}

interface FeedbackForm {
  kind: "feedback" | "bug" | "help"
  message: string
}

const PLACEHOLDERS: Record<FeedbackForm["kind"], string> = {
  feedback: "What would make Calkit work better for your research?",
  bug: "What did you do, what did you expect, and what happened instead?",
  help: "What are you trying to do, and where are you stuck?",
}

/**
 * A way to reach a person without leaving the app.
 *
 * The community links are kept alongside the form rather than behind it:
 * some questions get a faster answer on Discord, and a hub with no email
 * configured answers the form with a 503, which would otherwise be a dead
 * end.
 */
const HelpFeedback = ({ isOpen, onClose }: HelpFeedbackProps) => {
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<FeedbackForm>({
    mode: "onBlur",
    defaultValues: { kind: "feedback", message: "" },
  })
  const kind = watch("kind")
  const mutation = useMutation({
    mutationFn: (data: FeedbackForm) =>
      MiscService.postFeedback({
        feedbackPost: {
          kind: data.kind,
          message: data.message,
          // Which page they were on when they hit send, so a bug report
          // doesn't cost a round trip to ask.
          page: window.location.pathname + window.location.search,
        },
      }).then((response) => response.data),
    onSuccess: (data) => {
      showToast("Sent", data.message, "success")
      reset()
      onClose()
    },
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const onSubmit: SubmitHandler<FeedbackForm> = (data) => mutation.mutate(data)
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
        <ModalHeader>Help and feedback</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <FormControl mb={4}>
            <FormLabel htmlFor="kind">What's this about?</FormLabel>
            <Select id="kind" {...register("kind")}>
              <option value="feedback">Feedback or a feature idea</option>
              <option value="bug">Something's broken</option>
              <option value="help">I'm stuck and need help</option>
            </Select>
          </FormControl>
          <FormControl isRequired isInvalid={!!errors.message}>
            <FormLabel htmlFor="message">Your message</FormLabel>
            <Textarea
              id="message"
              {...register("message", {
                required: "A message is required.",
                maxLength: {
                  value: 5000,
                  message: "Please keep it under 5000 characters.",
                },
              })}
              placeholder={PLACEHOLDERS[kind]}
              rows={6}
            />
            {errors.message ? (
              <FormErrorMessage>{errors.message.message}</FormErrorMessage>
            ) : null}
          </FormControl>
          <Divider my={4} />
          <Text fontSize="sm" color="ui.dim" mb={2}>
            Or reach the community directly:
          </Text>
          <HStack spacing={4} wrap="wrap">
            <Link
              fontSize="sm"
              variant="blue"
              href="https://docs.calkit.org"
              isExternal
            >
              Docs <ExternalLinkIcon mb={0.5} />
            </Link>
            <Link
              fontSize="sm"
              variant="blue"
              href="https://discord.gg/m2MBC79HzD"
              isExternal
            >
              Discord <ExternalLinkIcon mb={0.5} />
            </Link>
            <Link
              fontSize="sm"
              variant="blue"
              href="https://github.com/orgs/calkit/discussions"
              isExternal
            >
              Discussions <ExternalLinkIcon mb={0.5} />
            </Link>
            <Link
              fontSize="sm"
              variant="blue"
              href="https://github.com/calkit/calkit/issues"
              isExternal
            >
              Issue tracker <ExternalLinkIcon mb={0.5} />
            </Link>
          </HStack>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={isSubmitting || mutation.isPending}
          >
            Send
          </Button>
          <Button onClick={onClose}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default HelpFeedback
