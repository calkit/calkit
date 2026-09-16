import {
  Badge,
  Box,
  Code,
  Heading,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"

import { FeedbackService } from "../../client"
import { formatTimestamp } from "../../lib/strings"

/**
 * Who has voted for which not-yet-built feature.
 *
 * Shown with the feedback, since both are users telling us what to build
 * next; a vote is the cheap version of a message.
 */
const FeatureVotesTable = () => {
  const votesQuery = useQuery({
    queryKey: ["admin", "feature-votes"],
    queryFn: () =>
      FeedbackService.getFeatureVotes().then((response) => response.data),
  })
  return (
    <Box mt={10}>
      <Heading size="lg" lineHeight="1" mb={4}>
        Feature votes
      </Heading>
      {votesQuery.isPending ? (
        <Text color="ui.dim">Loading</Text>
      ) : votesQuery.isError ? (
        <Text color="red.400">Could not load feature votes.</Text>
      ) : (
        (votesQuery.data ?? []).map((feature) => (
          <Box key={feature.feature} mb={6}>
            <Text fontWeight="semibold" mb={2}>
              <Code>{feature.feature}</Code>{" "}
              <Badge ml={1} colorScheme={feature.count ? "green" : "gray"}>
                {feature.count} {feature.count === 1 ? "vote" : "votes"}
              </Badge>
            </Text>
            {feature.voters.length ? (
              <TableContainer>
                <Table size="sm">
                  <Thead>
                    <Tr>
                      <Th>User</Th>
                      <Th>Email</Th>
                      <Th>Voted</Th>
                    </Tr>
                  </Thead>
                  <Tbody>
                    {feature.voters.map((voter) => (
                      <Tr key={`${feature.feature}:${voter.email}`}>
                        <Td>
                          {voter.full_name ?? voter.account_name ?? ""}
                          {voter.account_name ? (
                            <Text as="span" color="ui.dim" ml={1}>
                              @{voter.account_name}
                            </Text>
                          ) : null}
                        </Td>
                        <Td>{voter.email}</Td>
                        <Td whiteSpace="nowrap">
                          {formatTimestamp(voter.created)}
                        </Td>
                      </Tr>
                    ))}
                  </Tbody>
                </Table>
              </TableContainer>
            ) : (
              <Text fontSize="sm" color="ui.dim">
                No votes yet.
              </Text>
            )}
          </Box>
        ))
      )}
    </Box>
  )
}

export default FeatureVotesTable
