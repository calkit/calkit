import {
  Button,
  Checkbox,
  FormControl,
  FormErrorMessage,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Select,
  Text,
} from "@chakra-ui/react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { type SubmitHandler, useForm } from "react-hook-form"

import {
  type UserPublic,
  type UserSubscriptionAdminUpdate,
  UsersService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { handleError } from "../../lib/errors"

interface EditUserSubscriptionProps {
  user: UserPublic
  isOpen: boolean
  onClose: () => void
}

interface SubscriptionForm {
  plan_name: UserSubscriptionAdminUpdate["plan_name"]
  period_months: string
  price: number
  // A date input's YYYY-MM-DD, treated as UTC midnight
  paid_until: string
  is_active: boolean
}

const EditUserSubscription = ({
  user,
  isOpen,
  onClose,
}: EditUserSubscriptionProps) => {
  const queryClient = useQueryClient()
  const showToast = useCustomToast()
  const sub = user.subscription
  const {
    register,
    handleSubmit,
    reset,
    watch,
    formState: { errors, isSubmitting, isDirty },
  } = useForm<SubscriptionForm>({
    mode: "onBlur",
    criteriaMode: "all",
    defaultValues: {
      plan_name:
        (sub?.plan_name as SubscriptionForm["plan_name"] | undefined) ?? "free",
      period_months: String(sub?.period_months ?? 1),
      price: sub?.price ?? 0,
      paid_until: sub?.paid_until ? sub.paid_until.slice(0, 10) : "",
      is_active: sub?.is_active ?? true,
    },
  })
  const planName = watch("plan_name")
  const mutation = useMutation({
    mutationFn: (data: UserSubscriptionAdminUpdate) =>
      UsersService.putUserSubscriptionAdmin({
        user_id: user.id,
        userSubscriptionAdminUpdate: data,
      }).then((response) => response.data),
    onSuccess: () => {
      showToast("Success!", "Subscription updated.", "success")
      onClose()
    },
    onError: (err: AxiosError) => {
      handleError(err, showToast)
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] })
    },
  })
  const onSubmit: SubmitHandler<SubscriptionForm> = (data) => {
    mutation.mutate({
      plan_name: data.plan_name,
      period_months: Number(data.period_months) as 1 | 12,
      price: data.price,
      paid_until: data.paid_until ? `${data.paid_until}T00:00:00Z` : null,
      is_active: data.is_active,
    })
  }
  const onCancel = () => {
    reset()
    onClose()
  }
  return (
    <Modal
      isOpen={isOpen}
      onClose={onCancel}
      size={{ base: "sm", md: "md" }}
      isCentered
      motionPreset="none"
    >
      <ModalOverlay />
      <ModalContent as="form" onSubmit={handleSubmit(onSubmit)}>
        <ModalHeader>Edit subscription</ModalHeader>
        <ModalCloseButton />
        <ModalBody pb={6}>
          <Text fontSize="sm" color="ui.dim" mb={4}>
            {user.email}
            {sub?.processor ? ` · ${sub.processor}` : ""}
            {sub?.processor_subscription_id
              ? ` · ${sub.processor_subscription_id}`
              : ""}
          </Text>
          <FormControl>
            <FormLabel htmlFor="plan_name">Plan</FormLabel>
            <Select id="plan_name" {...register("plan_name")}>
              <option value="free">Free</option>
              <option value="standard">Standard</option>
              <option value="professional">Professional</option>
            </Select>
          </FormControl>
          <FormControl mt={4}>
            <FormLabel htmlFor="period_months">Period</FormLabel>
            <Select id="period_months" {...register("period_months")}>
              <option value="1">Monthly</option>
              <option value="12">Annual</option>
            </Select>
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.price}>
            <FormLabel htmlFor="price">Monthly price (USD)</FormLabel>
            <Input
              id="price"
              type="number"
              step="0.01"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              {...register("price", {
                valueAsNumber: true,
                min: { value: 0, message: "Price can't be negative" },
              })}
            />
            {errors.price && (
              <FormErrorMessage>{errors.price.message}</FormErrorMessage>
            )}
          </FormControl>
          <FormControl mt={4} isInvalid={!!errors.paid_until}>
            <FormLabel htmlFor="paid_until">Paid until (UTC)</FormLabel>
            <Input
              id="paid_until"
              type="date"
              autoComplete="off"
              data-form-type="other"
              data-lpignore="true"
              {...register("paid_until", {
                validate: (value) =>
                  planName === "free" ||
                  Boolean(value) ||
                  "Required for a paid plan",
              })}
            />
            {errors.paid_until && (
              <FormErrorMessage>{errors.paid_until.message}</FormErrorMessage>
            )}
          </FormControl>
          <FormControl mt={4}>
            <Checkbox {...register("is_active")} colorScheme="teal">
              Active
            </Checkbox>
          </FormControl>
        </ModalBody>
        <ModalFooter gap={3}>
          <Button
            variant="primary"
            type="submit"
            isLoading={isSubmitting || mutation.isPending}
            isDisabled={!isDirty}
          >
            Save
          </Button>
          <Button onClick={onCancel}>Cancel</Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default EditUserSubscription
