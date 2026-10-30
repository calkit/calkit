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
import { useNavigate, useSearch } from "@tanstack/react-router"
import { QRCodeSVG } from "qrcode.react"
import { useState } from "react"

import { MachinesService, UsersService } from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import Tooltip from "../Common/Tooltip"
import { timeAgo } from "../Projects/RecentChanges"

// What the API says when setting up two-factor authentication needs a
// verified email first, from app/users.py
const VERIFY_EMAIL_FIRST = "Verify your email first"

// Opening sessions on a machine takes an authenticator code, since it
// gives shell access to it
function TwoFactor() {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const { user } = useAuth()
  // Setup emails a code, so the address has to be verified first, which
  // happens inline: a code is sent, and entering it carries on to setup.
  // The step is kept in the URL, so a reload lands back on it.
  const { verify_2fa } = useSearch({ from: "/_layout/settings" })
  const navigate = useNavigate({ from: "/settings" })
  const verifying = Boolean(verify_2fa) && !user?.email_verified
  const setVerifying = (on: boolean) =>
    navigate({
      search: (prev) => ({ ...prev, verify_2fa: on || undefined }),
    })
  const [verifyCode, setVerifyCode] = useState("")
  const [setup, setSetup] = useState<{
    secret: string
    otpauth_uri: string
  } | null>(null)
  const [code, setCode] = useState("")
  const [emailCode, setEmailCode] = useState("")
  const statusQuery = useQuery({
    queryKey: ["user", "totp"],
    // With the cookie that says whether a code was entered recently
    queryFn: () =>
      UsersService.getUserTotp({ withCredentials: true }).then((r) => r.data),
  })
  const onSettled = () => {
    setCode("")
    queryClient.invalidateQueries({ queryKey: ["user", "totp"] })
  }
  const onError = (e: any) =>
    showToast("Error", e.response?.data?.detail ?? e.message, "error")
  const sendVerifyMutation = useMutation({
    mutationFn: () => UsersService.postUserEmailVerification(),
    onSuccess: () => {
      setVerifyCode("")
      setVerifying(true)
    },
    onError: (e: any): void => {
      const detail = e.response?.data?.detail ?? ""
      if (detail === "This email is already verified") {
        // Verified since this page loaded, so setup can go ahead
        startMutation.mutate()
      } else if (detail.startsWith("A code was just sent") && !verifying) {
        // One is already on its way, so it's entered rather than resent
        setVerifyCode("")
        setVerifying(true)
      } else {
        onError(e)
      }
    },
  })
  const startMutation = useMutation({
    mutationFn: () => UsersService.postUserTotp().then((r) => r.data),
    onSuccess: setSetup,
    onError: (e: any): void =>
      e.response?.data?.detail === VERIFY_EMAIL_FIRST
        ? sendVerifyMutation.mutate()
        : onError(e),
  })
  const confirmVerifyMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserEmailVerificationConfirm({
        emailVerificationConfirm: { code: verifyCode },
      }),
    onSuccess: () => {
      setVerifying(false)
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      startMutation.mutate()
    },
    onError,
  })
  const startSetup = () =>
    user && !user.email_verified
      ? sendVerifyMutation.mutate()
      : startMutation.mutate()
  const confirmMutation = useMutation({
    mutationFn: () =>
      // Counts as entering a code, which the API keeps in a cookie
      UsersService.postUserTotpConfirm(
        { totpConfirm: { code, email_code: emailCode } },
        { withCredentials: true },
      ).then((r) => r.data),
    onSuccess: () => {
      setEmailCode("")
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
          {statusQuery.data.verified_until && (
            <Text fontSize="sm" color="ui.dim">
              Code entered, good until{" "}
              {new Date(statusQuery.data.verified_until).toLocaleString()}
            </Text>
          )}
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
          <Text fontSize="sm" mb={2}>
            Also enter the code we just emailed you.
          </Text>
          <Flex gap={2}>
            {codeInput}
            <Input
              size="sm"
              maxW="160px"
              placeholder="Emailed code"
              value={emailCode}
              onChange={(e) => setEmailCode(e.target.value)}
              inputMode="numeric"
              autoComplete="off"
            />
            <Button
              size="sm"
              variant="primary"
              isDisabled={code.length < 6 || emailCode.length < 6}
              isLoading={confirmMutation.isPending}
              onClick={() => confirmMutation.mutate()}
            >
              Confirm
            </Button>
          </Flex>
        </>
      ) : verifying ? (
        <>
          <Text mb={2}>
            First, confirm your email: enter the code we sent to {user?.email}.
          </Text>
          <Flex gap={2} align="center" wrap="wrap">
            <Input
              size="sm"
              maxW="140px"
              placeholder="123456"
              value={verifyCode}
              onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ""))}
              inputMode="numeric"
              maxLength={6}
              autoComplete="one-time-code"
            />
            <Button
              size="sm"
              variant="primary"
              isDisabled={verifyCode.length !== 6}
              isLoading={
                confirmVerifyMutation.isPending || startMutation.isPending
              }
              onClick={() => confirmVerifyMutation.mutate()}
            >
              Verify
            </Button>
            <Button
              size="sm"
              variant="ghost"
              isLoading={sendVerifyMutation.isPending}
              onClick={() => sendVerifyMutation.mutate()}
            >
              Resend code
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setVerifying(false)}
            >
              Cancel
            </Button>
          </Flex>
        </>
      ) : (
        <Flex align="center" gap={2}>
          <Text>Required to connect to workspaces.</Text>
          <Button
            size="sm"
            variant="primary"
            isLoading={startMutation.isPending || sendVerifyMutation.isPending}
            onClick={startSetup}
          >
            Set up
          </Button>
        </Flex>
      )}
    </Box>
  )
}

function Machines() {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  // The machine whose revoke button has been clicked once
  const [confirming, setConfirming] = useState<string | null>(null)
  const machinesQuery = useQuery({
    queryKey: ["user", "machines"],
    queryFn: () => MachinesService.getMachines().then((r) => r.data),
    refetchInterval: 30000,
  })
  const revokeMutation = useMutation({
    mutationFn: (machineId: string) =>
      MachinesService.deleteMachine({ machine_id: machineId }),
    onSuccess: () => setConfirming(null),
    onError: (e: any) =>
      showToast("Could not revoke machine", e.message, "error"),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["user", "machines"] }),
  })
  const restartMutation = useMutation({
    mutationFn: (machineId: string) =>
      MachinesService.postMachineRestart({ machine_id: machineId }),
    onError: (e: any) =>
      showToast("Could not restart link", e.message, "error"),
    onSettled: () =>
      queryClient.invalidateQueries({ queryKey: ["user", "machines"] }),
  })
  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Machines
      </Heading>
      <TwoFactor />
      <Text mb={4}>
        To connect a machine, install the Calkit CLI on it and run{" "}
        <Code>calkit hub link install</Code>.
      </Text>
      <TableContainer>
        <Table size="sm">
          <Thead>
            <Tr>
              <Th>Name</Th>
              <Th>Host</Th>
              <Th>Calkit</Th>
              <Th>Machine ID</Th>
              <Th>Created</Th>
              <Th>Last seen</Th>
              <Th>Workspaces</Th>
              <Th />
            </Tr>
          </Thead>
          <Tbody>
            {machinesQuery.isPending ? (
              <Tr>
                {new Array(8).fill(null).map((_, index) => (
                  <Td key={index}>
                    <SkeletonText noOfLines={1} paddingBlock="16px" />
                  </Td>
                ))}
              </Tr>
            ) : (
              machinesQuery.data?.map((machine) => (
                <Tr key={machine.id}>
                  <Td>
                    <Flex align="center" gap={2}>
                      <Box
                        w={2}
                        h={2}
                        borderRadius="full"
                        bg={
                          machine.is_online
                            ? "ui.success"
                            : machine.is_asleep
                              ? "yellow.400"
                              : "gray.400"
                        }
                      />
                      {machine.name}
                      {machine.is_asleep && (
                        <Badge fontSize="2xs">asleep</Badge>
                      )}
                    </Flex>
                  </Td>
                  <Td>
                    {machine.hostname}
                    {machine.platform ? ` (${machine.platform})` : ""}
                  </Td>
                  <Td>
                    <Flex align="center" gap={2}>
                      {/* Dev versions carry a long local suffix */}
                      {machine.calkit_version?.split("+")[0]}
                      {machine.restart_pending && (
                        <Tooltip label="Restarts when idle">
                          <Badge fontSize="2xs">restart pending</Badge>
                        </Tooltip>
                      )}
                    </Flex>
                  </Td>
                  {/* To tell an impostor from the real thing */}
                  <Td>
                    {machine.system_machine_id && (
                      <Tooltip label={machine.system_machine_id}>
                        <Code fontSize="xs">
                          {machine.system_machine_id.slice(0, 12)}
                        </Code>
                      </Tooltip>
                    )}
                  </Td>
                  <Td>
                    {machine.created &&
                      new Date(`${machine.created}Z`).toLocaleDateString()}
                  </Td>
                  <Td>
                    {machine.last_seen ? (
                      <Tooltip
                        label={new Date(
                          `${machine.last_seen}Z`,
                        ).toLocaleString()}
                      >
                        {timeAgo(`${machine.last_seen}Z`)}
                      </Tooltip>
                    ) : (
                      "Never"
                    )}
                  </Td>
                  <Td>{machine.workspace_count}</Td>
                  <Td>
                    {machine.is_online && !machine.restart_pending && (
                      <Button
                        size="xs"
                        variant="outline"
                        mr={2}
                        isLoading={
                          restartMutation.isPending &&
                          restartMutation.variables === machine.id
                        }
                        onClick={() =>
                          restartMutation.mutate(String(machine.id))
                        }
                      >
                        Restart
                      </Button>
                    )}
                    <Button
                      size="xs"
                      colorScheme="red"
                      variant={confirming === machine.id ? "solid" : "outline"}
                      isLoading={
                        revokeMutation.isPending &&
                        revokeMutation.variables === machine.id
                      }
                      onClick={() =>
                        confirming === machine.id
                          ? revokeMutation.mutate(String(machine.id))
                          : setConfirming(String(machine.id))
                      }
                      onBlur={() => setConfirming(null)}
                    >
                      {confirming === machine.id ? "Confirm revoke" : "Revoke"}
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

export default Machines
