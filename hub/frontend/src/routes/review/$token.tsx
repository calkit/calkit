import {
  Badge,
  Box,
  Button,
  Container,
  FormControl,
  FormLabel,
  HStack,
  Heading,
  Icon,
  Input,
  Spinner,
  Text,
  Textarea,
  VStack,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { createFileRoute } from "@tanstack/react-router"
import type { AxiosError } from "axios"
import { useRef, useState } from "react"
import { FaUpload } from "react-icons/fa"
import { FiDownload } from "react-icons/fi"

import { ProjectsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { apiUrl } from "../../lib/core"
import { handleError } from "../../lib/errors"

export const Route = createFileRoute("/review/$token")({
  component: Review,
})

// The page a reviewer lands on from a request link: what's being asked,
// the Word copy to download, and a place to hand it back. No account.
function Review() {
  const { token } = Route.useParams()
  const showToast = useCustomToast()
  const cardBg = useColorModeValue("white", "gray.800")
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [message, setMessage] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [done, setDone] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const requestQuery = useQuery({
    queryKey: ["contrib-requests", token],
    queryFn: () =>
      ProjectsService.getContribRequestByToken({ token }).then((r) => r.data),
    retry: false,
  })
  const submit = useMutation({
    mutationFn: () => {
      if (!file) throw new Error("Choose the document to send back")
      return ProjectsService.postContribRequestResponse({
        token,
        bodyProjectsPostContribRequestResponse: {
          file,
          responder_name: name.trim() || null,
          responder_email: email.trim() || null,
          message: message.trim() || null,
        },
      }).then((r) => r.data)
    },
    onSuccess: () => setDone(true),
    onError: (err: AxiosError) => handleError(err, showToast),
  })
  const req = requestQuery.data
  const permissionLabel: Record<string, string> = {
    view: "have a look",
    comment: "comment on it",
    suggest: "suggest changes and comment",
    edit: "edit it",
  }
  return (
    <Container maxW="2xl" py={12}>
      {requestQuery.isPending ? (
        <VStack py={16}>
          <Spinner size="lg" />
        </VStack>
      ) : requestQuery.isError || !req ? (
        <VStack py={16} spacing={2}>
          <Heading size="md">This link isn't valid</Heading>
          <Text color="gray.500">
            It may have been revoked, or copied incompletely. Ask whoever sent
            it for a new one.
          </Text>
        </VStack>
      ) : (
        <VStack align="stretch" spacing={6}>
          <Box>
            <Text fontSize="sm" color="gray.500">
              {req.requester_name} asked you to{" "}
              {permissionLabel[req.permission] ?? "review"}
            </Text>
            <Heading size="lg" mt={1}>
              {req.title}
            </Heading>
            <HStack mt={2} spacing={2} wrap="wrap">
              <Badge>
                {req.owner_account_display_name} / {req.project_title}
              </Badge>
              {req.target_path && (
                <Badge variant="outline">{req.target_path}</Badge>
              )}
              {req.git_rev_abbrev && (
                <Badge variant="outline">rev {req.git_rev_abbrev}</Badge>
              )}
              {req.due_at && (
                <Badge colorScheme="orange">
                  Due {new Date(req.due_at).toLocaleDateString()}
                </Badge>
              )}
            </HStack>
          </Box>
          {req.message && (
            <Box bg={cardBg} borderWidth={1} borderRadius="lg" p={4}>
              <Text whiteSpace="pre-wrap">{req.message}</Text>
            </Box>
          )}
          {req.document_path && (
            <Box>
              <Heading size="sm" mb={2}>
                1. Get the document
              </Heading>
              <Text fontSize="sm" color="gray.500" mb={2}>
                Open it in Microsoft Word. Track Changes is already on, so edit
                as you normally would and leave comments where you have
                questions.
              </Text>
              <Button
                as="a"
                href={`${apiUrl}/contrib-requests/${encodeURIComponent(token)}/document`}
                leftIcon={<Icon as={FiDownload} />}
                variant="primary"
                size="sm"
              >
                Download {req.document_path.split("/").pop()}
              </Button>
            </Box>
          )}
          <Box>
            <Heading size="sm" mb={2}>
              {req.document_path ? "2. " : ""}Send it back
            </Heading>
            {done ? (
              <Box bg={cardBg} borderWidth={1} borderRadius="lg" p={4}>
                <Text fontWeight="semibold">Thank you.</Text>
                <Text fontSize="sm" color="gray.500">
                  Your marked-up copy is with {req.requester_name} now. You can
                  close this page.
                </Text>
              </Box>
            ) : !req.can_respond ? (
              <Text fontSize="sm" color="gray.500">
                This request is no longer accepting responses.
              </Text>
            ) : (
              <VStack
                align="stretch"
                spacing={3}
                bg={cardBg}
                borderWidth={1}
                borderRadius="lg"
                p={4}
              >
                <FormControl isRequired>
                  <FormLabel fontSize="sm">Your reviewed copy</FormLabel>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".docx"
                    hidden
                    onChange={(ev) => setFile(ev.target.files?.[0] ?? null)}
                  />
                  <HStack>
                    <Button
                      size="sm"
                      leftIcon={<Icon as={FaUpload} />}
                      onClick={() => fileInput.current?.click()}
                    >
                      Choose .docx
                    </Button>
                    <Text fontSize="sm" color="gray.500" noOfLines={1}>
                      {file ? file.name : "No file chosen"}
                    </Text>
                  </HStack>
                </FormControl>
                <HStack align="start">
                  <FormControl>
                    <FormLabel fontSize="sm">Your name</FormLabel>
                    <Input
                      size="sm"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                  </FormControl>
                  <FormControl
                    isRequired={req.identity_requirement === "email"}
                  >
                    <FormLabel fontSize="sm">Your email</FormLabel>
                    <Input
                      size="sm"
                      type="email"
                      value={email}
                      placeholder={req.responder_email ?? ""}
                      onChange={(e) => setEmail(e.target.value)}
                    />
                  </FormControl>
                </HStack>
                <FormControl>
                  <FormLabel fontSize="sm">A note, if you like</FormLabel>
                  <Textarea
                    size="sm"
                    rows={3}
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                  />
                </FormControl>
                <Button
                  variant="primary"
                  alignSelf="flex-end"
                  isDisabled={!file}
                  isLoading={submit.isPending}
                  onClick={() => submit.mutate()}
                >
                  Send
                </Button>
              </VStack>
            )}
          </Box>
          <Text fontSize="xs" color="gray.500">
            Powered by Calkit. Your document goes straight into the project's
            own repository, where its author merges your changes and comments
            into the source.
          </Text>
        </VStack>
      )}
    </Container>
  )
}
