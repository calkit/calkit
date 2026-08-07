import {
  Button,
  Container,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Image,
  Input,
  Link,
  Text,
} from "@chakra-ui/react"
import { useMutation } from "@tanstack/react-query"
import {
  Link as RouterLink,
  createFileRoute,
  redirect,
  useNavigate,
} from "@tanstack/react-router"
import { type SubmitHandler, useForm } from "react-hook-form"

import Logo from "/assets/images/calkit-no-bg.svg"
import { LoginService, UsersService } from "../client"
import type { ApiError } from "../client/core/ApiError"
import { isLoggedIn } from "../hooks/useAuth"
import useCustomToast from "../hooks/useCustomToast"
import { popPostLoginRedirect, storeTokens } from "../lib/auth"
import { handleError } from "../lib/errors"

export const Route = createFileRoute("/signup")({
  component: SignUp,
  beforeLoad: async () => {
    if (isLoggedIn()) {
      const stored = popPostLoginRedirect()
      throw redirect({ to: stored || "/" })
    }
  },
})

interface SignUpForm {
  full_name: string
  account_name: string
  email: string
  password: string
}

function SignUp() {
  const navigate = useNavigate()
  const showToast = useCustomToast()
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<SignUpForm>({ mode: "onBlur" })

  const mutation = useMutation({
    mutationFn: async (data: SignUpForm) => {
      await UsersService.registerUser({
        requestBody: {
          email: data.email,
          password: data.password,
          full_name: data.full_name,
          account_name: data.account_name,
        },
      })
      const resp = await LoginService.accessToken({
        formData: { username: data.email, password: data.password },
      })
      storeTokens(resp.access_token, resp.refresh_token)
    },
    onSuccess: () => {
      showToast(
        "Welcome to Calkit!",
        "Your account has been created.",
        "success",
      )
      const redirectTo = popPostLoginRedirect()
      navigate({ to: redirectTo || "/" })
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  const onSubmit: SubmitHandler<SignUpForm> = (data) => {
    mutation.mutate(data)
  }

  return (
    <Container
      h="100vh"
      maxW="xs"
      justifyContent="center"
      gap={3}
      centerContent
    >
      <Image src={Logo} alt="Logo" height="120px" alignSelf="center" mb={-4} />
      <Text fontSize="lg" fontWeight="bold">
        Create your account
      </Text>
      <form onSubmit={handleSubmit(onSubmit)} style={{ width: "100%" }}>
        <FormControl isInvalid={!!errors.full_name} mb={3}>
          <FormLabel htmlFor="full_name">Name</FormLabel>
          <Input
            id="full_name"
            {...register("full_name", { required: "Name is required" })}
            placeholder="Your name"
          />
          {errors.full_name && (
            <FormErrorMessage>{errors.full_name.message}</FormErrorMessage>
          )}
        </FormControl>
        <FormControl isInvalid={!!errors.account_name} mb={3}>
          <FormLabel htmlFor="account_name">Username</FormLabel>
          <Input
            id="account_name"
            {...register("account_name", {
              required: "Username is required",
              pattern: {
                value: /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,62}[a-zA-Z0-9])?$/,
                message: "Use letters, numbers, and dashes",
              },
            })}
            placeholder="Choose a unique username"
          />
          {errors.account_name ? (
            <FormErrorMessage>{errors.account_name.message}</FormErrorMessage>
          ) : (
            <Text fontSize="xs" color="ui.dim" mt={1}>
              Your account name, used in your project URLs.
            </Text>
          )}
        </FormControl>
        <FormControl isInvalid={!!errors.email} mb={3}>
          <FormLabel htmlFor="email">Email</FormLabel>
          <Input
            id="email"
            type="email"
            {...register("email", { required: "Email is required" })}
            placeholder="you@example.com"
          />
          {errors.email && (
            <FormErrorMessage>{errors.email.message}</FormErrorMessage>
          )}
        </FormControl>
        <FormControl isInvalid={!!errors.password} mb={4}>
          <FormLabel htmlFor="password">Password</FormLabel>
          <Input
            id="password"
            type="password"
            {...register("password", {
              required: "Password is required",
              minLength: { value: 8, message: "At least 8 characters" },
            })}
            placeholder="Choose a password"
          />
          {errors.password && (
            <FormErrorMessage>{errors.password.message}</FormErrorMessage>
          )}
        </FormControl>
        <Button
          variant="primary"
          type="submit"
          width="full"
          isLoading={isSubmitting || mutation.isPending}
        >
          Sign up
        </Button>
      </form>
      <Text fontSize="sm">
        Already have an account?{" "}
        <Link as={RouterLink} to="/login" variant="default">
          Sign in
        </Link>
      </Text>
    </Container>
  )
}
