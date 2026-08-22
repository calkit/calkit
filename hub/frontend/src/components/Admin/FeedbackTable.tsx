import {
  Badge,
  Box,
  Button,
  Flex,
  Heading,
  SkeletonText,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"

import { MiscService } from "../../client"
import { formatTimestamp } from "../../lib/strings"

const KIND_LABELS: Record<string, { label: string; scheme: string }> = {
  feedback: { label: "Feedback", scheme: "teal" },
  bug: { label: "Bug", scheme: "red" },
  help: { label: "Help", scheme: "orange" },
}

/**
 * What users have sent through the in-app help form.
 *
 * Open items first and resolved ones hidden by default, since the list is
 * a queue to work through rather than an archive to read.
 */
const FeedbackTable = () => {
  const queryClient = useQueryClient()
  const [showResolved, setShowResolved] = useState(false)
  const feedbackQuery = useQuery({
    queryKey: ["feedback"],
    queryFn: () => MiscService.getFeedback().then((response) => response.data),
  })
  const resolveMutation = useMutation({
    mutationFn: ({ id, resolved }: { id: string; resolved: boolean }) =>
      MiscService.patchFeedback({
        feedback_id: id,
        feedbackPatch: { resolved },
      }).then((response) => response.data),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["feedback"] }),
  })
  const all = feedbackQuery.data ?? []
  const visible = showResolved ? all : all.filter((f) => !f.resolved)
  const openCount = all.filter((f) => !f.resolved).length
  return (
    <Box mt={12}>
      {/* Centered, not baseline-aligned: a small button's baseline sits well
          below the optical middle of a heading this size. */}
      <Flex align="center" gap={3} mb={4} minH="40px">
        <Heading size="lg" lineHeight="1">
          User feedback
        </Heading>
        {openCount > 0 ? (
          <Badge colorScheme="teal">{openCount} open</Badge>
        ) : null}
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setShowResolved((v) => !v)}
        >
          {showResolved ? "Hide resolved" : "Show resolved"}
        </Button>
      </Flex>
      {feedbackQuery.isPending ? (
        <SkeletonText noOfLines={3} />
      ) : visible.length === 0 ? (
        <Text color="ui.dim">
          {all.length === 0
            ? "Nothing has come in yet."
            : "Nothing open. Everything sent in has been dealt with."}
        </Text>
      ) : (
        <TableContainer>
          <Table size={{ base: "sm", md: "md" }}>
            <Thead>
              <Tr>
                <Th>Kind</Th>
                <Th>From</Th>
                <Th>Message</Th>
                <Th>Page</Th>
                <Th>When</Th>
                <Th>Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {visible.map((item) => {
                const kind = KIND_LABELS[item.kind] ?? {
                  label: item.kind,
                  scheme: "gray",
                }
                return (
                  <Tr key={item.id} opacity={item.resolved ? 0.5 : 1}>
                    <Td>
                      <Badge colorScheme={kind.scheme}>{kind.label}</Badge>
                    </Td>
                    <Td fontSize="sm">
                      {item.user_full_name ? (
                        <Text>{item.user_full_name}</Text>
                      ) : null}
                      <Text color="ui.dim">{item.user_email}</Text>
                    </Td>
                    {/* Kept whole rather than truncated: the message is the
                        only thing on this page worth reading in full. */}
                    <Td whiteSpace="pre-wrap" maxW="420px">
                      {item.message}
                    </Td>
                    <Td fontSize="xs" color="ui.dim" isTruncated maxW="140px">
                      {item.page ?? "—"}
                    </Td>
                    <Td fontSize="xs" color="ui.dim" whiteSpace="nowrap">
                      {formatTimestamp(item.created)}
                    </Td>
                    <Td>
                      <Button
                        size="xs"
                        isLoading={
                          resolveMutation.isPending &&
                          resolveMutation.variables?.id === item.id
                        }
                        onClick={() =>
                          resolveMutation.mutate({
                            id: item.id,
                            resolved: !item.resolved,
                          })
                        }
                      >
                        {item.resolved ? "Reopen" : "Resolve"}
                      </Button>
                    </Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}

export default FeedbackTable
