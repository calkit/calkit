import {
  Badge,
  Box,
  Button,
  Container,
  Flex,
  FormControl,
  FormErrorMessage,
  FormHelperText,
  FormLabel,
  Heading,
  Input,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate, useSearch } from "@tanstack/react-router"
import { type FormEvent, useState } from "react"
import { type SubmitHandler, useForm } from "react-hook-form"

import type { AxiosError } from "axios"
import { type UserPublic, type UserUpdateMe, UsersService } from "../../client"
import useAuth from "../../hooks/useAuth"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"
import { emailPattern } from "../../lib/strings"

/**
 * The inline step between "Verify" and a verified address: the code from
 * the email, with a way to ask for another.
 *
 * Open state lives in the `verify` search param, so a reload after
 * fetching the code from another tab lands back on this form.
 */
const VerifyEmailCode = ({ email }: { email: string }) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const navigate = useNavigate({ from: "/settings" })
  const [code, setCode] = useState("")
  const close = () =>
    navigate({ search: (prev) => ({ ...prev, verify: undefined }) })
  const resendMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserEmailVerification().then(
        (response) => response.data,
      ),
    onSuccess: () => {
      showToast("Code sent", `A new code is on its way to ${email}.`, "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const confirmMutation = useMutation({
    mutationFn: (value: string) =>
      UsersService.postUserEmailVerificationConfirm({
        emailVerificationConfirm: { code: value },
      }).then((response) => response.data),
    onSuccess: () => {
      showToast(
        "Email verified",
        "Thanks, your address is confirmed.",
        "success",
      )
      queryClient.invalidateQueries({ queryKey: ["currentUser"] })
      close()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  return (
    <Box
      as="form"
      mt={2}
      onSubmit={(e: FormEvent) => {
        e.preventDefault()
        confirmMutation.mutate(code)
      }}
    >
      <FormControl>
        <FormLabel htmlFor="verification_code" fontSize="sm">
          Enter the 6-digit code we emailed to {email}
        </FormLabel>
        <Flex gap={2} align="center" wrap="wrap">
          <Input
            id="verification_code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            inputMode="numeric"
            pattern="[0-9]{6}"
            maxLength={6}
            autoComplete="one-time-code"
            placeholder="123456"
            w="8em"
            fontFamily="mono"
            letterSpacing="0.2em"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            isDisabled={code.length !== 6}
            isLoading={confirmMutation.isPending}
          >
            Confirm
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => resendMutation.mutate()}
            isLoading={resendMutation.isPending}
          >
            Resend code
          </Button>
          <Button size="sm" variant="ghost" onClick={close}>
            Cancel
          </Button>
        </Flex>
        <FormHelperText>
          The code is good for 15 minutes. The email also has a link that does
          the same thing.
        </FormHelperText>
      </FormControl>
    </Box>
  )
}

const UserInformation = () => {
  const queryClient = useQueryClient()
  const color = useColorModeValue("inherit", "ui.light")
  const showToast = useCustomToast()
  const [editMode, setEditMode] = useState(false)
  const { user: currentUser } = useAuth()
  const { verify } = useSearch({ from: "/_layout/settings" })
  const navigate = useNavigate({ from: "/settings" })
  const sendCodeMutation = useMutation({
    mutationFn: () =>
      UsersService.postUserEmailVerification().then(
        (response) => response.data,
      ),
    onSuccess: () => {
      showToast(
        "Code sent",
        `Check ${currentUser?.email} for a 6-digit code.`,
        "success",
      )
      navigate({ search: (prev) => ({ ...prev, verify: true }) })
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
  })
  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { isSubmitting, errors, isDirty },
  } = useForm<UserPublic>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      full_name: currentUser?.full_name,
      email: currentUser?.email,
    },
  })

  const toggleEditMode = () => {
    setEditMode(!editMode)
  }

  const mutation = useMutation({
    mutationFn: (data: UserUpdateMe) =>
      UsersService.updateCurrentUser({ userUpdateMe: data }).then(
        (response) => response.data,
      ),
    onSuccess: () => {
      showToast("Success!", "User updated successfully.", "success")
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries()
    },
  })

  const onSubmit: SubmitHandler<UserUpdateMe> = async (data) => {
    mutation.mutate(data)
  }

  const onCancel = () => {
    reset()
    toggleEditMode()
  }

  return (
    <>
      <Container maxW="full">
        <Heading size="md" py={4}>
          User information
        </Heading>
        <Box
          w={{ sm: "full", md: "50%" }}
          as="form"
          onSubmit={handleSubmit(onSubmit)}
        >
          <FormControl>
            <FormLabel color={color} htmlFor="name">
              Full name
            </FormLabel>
            {editMode ? (
              <Input
                id="name"
                {...register("full_name", { maxLength: 30 })}
                type="text"
                size="md"
                w="auto"
              />
            ) : (
              <Text
                size="md"
                py={2}
                color={!currentUser?.full_name ? "ui.dim" : "inherit"}
                isTruncated
                maxWidth="250px"
              >
                {currentUser?.full_name || "N/A"}
              </Text>
            )}
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.email}>
            <FormLabel color={color} htmlFor="email">
              Email
            </FormLabel>
            {editMode ? (
              <Input
                id="email"
                {...register("email", {
                  required: "Email is required",
                  pattern: emailPattern,
                })}
                type="email"
                size="md"
                w="auto"
              />
            ) : (
              <Flex align="center" gap={2} py={2} wrap="wrap">
                <Text size="md" isTruncated maxWidth="250px">
                  {currentUser?.email}
                </Text>
                {currentUser?.email_verified ? (
                  <Badge colorScheme="green">Verified</Badge>
                ) : (
                  <>
                    <Badge colorScheme="orange">Unverified</Badge>
                    {!verify ? (
                      <Button
                        size="xs"
                        variant="outline"
                        onClick={() => sendCodeMutation.mutate()}
                        isLoading={sendCodeMutation.isPending}
                      >
                        Verify
                      </Button>
                    ) : null}
                  </>
                )}
              </Flex>
            )}
            {errors.email && (
              <FormErrorMessage>{errors.email.message}</FormErrorMessage>
            )}
          </FormControl>
          {verify && !editMode && !currentUser?.email_verified ? (
            <VerifyEmailCode email={currentUser?.email ?? ""} />
          ) : null}
          <Flex mt={4} gap={3}>
            <Button
              variant="primary"
              onClick={toggleEditMode}
              type={editMode ? "button" : "submit"}
              isLoading={editMode ? isSubmitting : false}
              isDisabled={editMode ? !isDirty || !getValues("email") : false}
            >
              {editMode ? "Save" : "Edit"}
            </Button>
            {editMode && (
              <Button onClick={onCancel} isDisabled={isSubmitting}>
                Cancel
              </Button>
            )}
          </Flex>
        </Box>
      </Container>
      <Container maxW="full" mt={6} />
    </>
  )
}

export default UserInformation
