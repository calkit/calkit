import {
  Badge,
  Box,
  Button,
  Code,
  Container,
  Flex,
  Heading,
  Input,
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
import { QRCodeSVG } from "qrcode.react"
import { useState } from "react"

import { OperatorsService, UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"

// Opening sessions on an Operator takes an authenticator code, since it
// gives shell access to the machine
function TwoFactor() {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const [setup, setSetup] = useState<{
    secret: string
    otpauth_uri: string
  } | null>(null)
  const [code, setCode] = useState("")
  const statusQuery = useQuery({
    queryKey: ["user", "totp"],
    queryFn: () => UsersService.getUserTotp().then((r) => r.data),
  })
  const onSettled = () => {
    setCode("")
    queryClient.invalidateQueries({ queryKey: ["user", "totp"] })
  }
  const onError = (e: any) =>
    showToast("Error", e.response?.data?.detail ?? e.message, "error")
  const startMutation = useMutation({
    mutationFn: () => UsersService.postUserTotp().then((r) => r.data),
    onSuccess: setSetup,
    onError,
  })
  const confirmMutation = useMutation({
    mutationFn: () => UsersService.postUserTotpConfirm({ totpCode: { code } }),
    onSuccess: () => {
      setSetup(null)
      showToast("Success!", "Two-factor authentication is on.", "success")
    },
    onError,
    onSettled,
  })
  const disableMutation = useMutation({
    mutationFn: () => UsersService.deleteUserTotp({ totpCode: { code } }),
    onSuccess: () =>
      showToast("Success!", "Two-factor authentication is off.", "success"),
    onError,
    onSettled,
  })
  const codeInput = (
    <Input
      size="sm"
      maxW="140px"
      placeholder="123456"
      value={code}
      onChange={(e) => setCode(e.target.value)}
      inputMode="numeric"
      autoComplete="one-time-code"
    />
  )
  if (statusQuery.isPending) return null
  return (
    <Box mb={6}>
      <Heading size="sm" mb={2}>
        Two-factor authentication
      </Heading>
      {statusQuery.data?.enabled ? (
        <Flex align="center" gap={2}>
          <Badge colorScheme="green">On</Badge>
          {codeInput}
          <Button
            size="sm"
            variant="outline"
            colorScheme="red"
            isDisabled={code.length < 6}
            isLoading={disableMutation.isPending}
            onClick={() => disableMutation.mutate()}
          >
            Turn off
          </Button>
        </Flex>
      ) : setup ? (
        <>
          <Text mb={2}>
            Scan this with an authenticator app, then enter the code it shows.
          </Text>
          <Box bg="white" p={2} display="inline-block" mb={2}>
            <QRCodeSVG value={setup.otpauth_uri} size={160} />
          </Box>
          <Text fontSize="sm" mb={2}>
            Or enter this key: <Code>{setup.secret}</Code>
          </Text>
          <Flex gap={2}>
            {codeInput}
            <Button
              size="sm"
              variant="primary"
              isDisabled={code.length < 6}
              isLoading={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              Confirm
            </Button>
          </Flex>
        </>
      ) : (
        <Flex align="center" gap={2}>
          <Text>Required to open sessions on your Operators.</Text>
          <Button
            size="sm"
            variant="primary"
            isLoading={startMutation.isPending}
            onClick={() => startMutation.mutate()}
          >
            Set up
          </Button>
        </Flex>
      )}
    </Box>
  )
}

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
      <TwoFactor />
      <Text mb={4}>
        Install one with <Code>calkit operator install</Code>.
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
