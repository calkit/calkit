import {
  Badge,
  Box,
  Button,
  Code,
  Container,
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

import { OperatorsService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"

function Operators() {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  // The Operator whose revoke button has been clicked once
  const [confirming, setConfirming] = useState<string | null>(null)
  const operatorsQuery = useQuery({
    queryKey: ["user", "operators"],
    queryFn: () => OperatorsService.getOperators().then((r) => r.data),
    refetchInterval: 30000,
  })
  const revokeMutation = useMutation({
    mutationFn: (operatorId: string) =>
      OperatorsService.deleteOperator({ operator_id: operatorId }),
    onSuccess: () => setConfirming(null),
    onError: (e: any) =>
      showToast("Could not revoke Operator", e.message, "error"),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["user", "operators"] }),
  })
  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Operators
      </Heading>
      <Text mb={4}>
        Install one with <Code>calkit install operator</Code>.
      </Text>
      <TableContainer>
        <Table size={{ base: "sm", md: "md" }}>
          <Thead>
            <Tr>
              <Th>Name</Th>
              <Th>Host</Th>
              <Th>Calkit</Th>
              <Th>Last seen</Th>
              <Th>Workspaces</Th>
              <Th />
            </Tr>
          </Thead>
          <Tbody>
            {operatorsQuery.isPending ? (
              <Tr>
                {new Array(6).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            ) : (
              operatorsQuery.data?.map((op) => (
                <Tr key={op.id}>
                  <Td>
                    <Flex align="center" gap={2}>
                      <Box
                        w={2}
                        h={2}
                        borderRadius="full"
                        bg={
                          op.is_online
                            ? "ui.success"
                            : op.is_asleep
                              ? "yellow.400"
                              : "gray.400"
                        }
                      />
                      {op.name}
                      {op.is_asleep && <Badge fontSize="2xs">asleep</Badge>}
                    </Flex>
                  </Td>
                  <Td>
                    {op.hostname}
                    {op.platform ? ` (${op.platform})` : ""}
                  </Td>
                  <Td>
                    {/* Dev versions carry a long local suffix */}
                    {op.calkit_version?.split("+")[0]}
                  </Td>
                  <Td>
                    {op.last_seen
                      ? new Date(`${op.last_seen}Z`).toLocaleString()
                      : "Never"}
                  </Td>
                  <Td>{op.workspaces?.length ?? 0}</Td>
                  <Td>
                    <Button
                      size="xs"
                      colorScheme="red"
                      variant={confirming === op.id ? "solid" : "outline"}
                      isLoading={
                        revokeMutation.isPending &&
                        revokeMutation.variables === op.id
                      }
                      onClick={() =>
                        confirming === op.id
                          ? revokeMutation.mutate(String(op.id))
                          : setConfirming(String(op.id))
                      }
                      onBlur={() => setConfirming(null)}
                    >
                      {confirming === op.id ? "Confirm revoke" : "Revoke"}
                    </Button>
                  </Td>
                </Tr>
              ))
            )}
          </Tbody>
        </Table>
      </TableContainer>
    </Container>
  )
}

export default Operators
