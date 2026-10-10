import { Alert, AlertIcon, Button, Input, Text } from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import { Link as RouterLink } from "@tanstack/react-router"
import { useState } from "react"

import { UsersService } from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { storeSecondFactorToken } from "../../lib/auth"
import {
  SECOND_FACTOR_REQUIRED,
  SECOND_FACTOR_SETUP_REQUIRED,
} from "./connection"

// What to do when the hub won't connect to Operators without a second
// factor: set one up, or enter a code
export default function SecondFactorPrompt({
  error,
  onVerified,
}: {
  error: string | null
  onVerified: () => void
}) {
  const showToast = useCustomToast()
  const [code, setCode] = useState("")
  const verifyMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserTotpVerify({ totpCode: { code } }).then(
        (r) => r.data,
      ),
    onSuccess: (data) => {
      storeSecondFactorToken(data.second_factor_token)
      setCode("")
      onVerified()
    },
    onError: (e: any) =>
      showToast("Error", e.response?.data?.detail ?? e.message, "error"),
  })
  const secondFactorError = error
  return (
    <>
      {secondFactorError === SECOND_FACTOR_SETUP_REQUIRED && (
        <Alert status="warning" borderRadius="md" mb={4}>
          <AlertIcon />
          <Text>
            Opening sessions and running things on your machines takes
            two-factor authentication.{" "}
            <RouterLink to="/settings" search={{ tab: "operators" }}>
              <Text as="span" color="ui.main" textDecoration="underline">
                Set it up
              </Text>
            </RouterLink>{" "}
            in your settings first.
          </Text>
        </Alert>
      )}
      {secondFactorError === SECOND_FACTOR_REQUIRED && (
        <Alert
          status="warning"
          borderRadius="md"
          mb={4}
          gap={2}
          flexWrap="wrap"
        >
          <AlertIcon />
          <Text>
            Opening sessions and running things on your machines takes a code
            from your authenticator app.
          </Text>
          <Input
            size="sm"
            maxW="140px"
            placeholder="123456"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && code.length >= 6) verifyMutation.mutate()
            }}
            inputMode="numeric"
            autoComplete="one-time-code"
          />
          <Button
            size="sm"
            variant="primary"
            isDisabled={code.length < 6}
            isLoading={verifyMutation.isPending}
            onClick={() => verifyMutation.mutate()}
          >
            Verify
          </Button>
        </Alert>
      )}
    </>
  )
}
