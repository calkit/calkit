import {
  Box,
  Button,
  Container,
  Flex,
  Heading,
  Text,
  Stack,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Spinner,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalCloseButton,
  ModalBody,
  useDisclosure,
} from "@chakra-ui/react"
import { useQuery } from "@tanstack/react-query"

import { type SubscriptionPlan, MiscService } from "../../client"
import useAuth from "../../hooks/useAuth"
import { formatTimestamp } from "../../lib/strings"
import PickSubscription from "./PickSubscription"

const Subscription = () => {
  const { user: currentUser } = useAuth()
  const { isOpen, onOpen, onClose } = useDisclosure()

  // Fetch available subscription plans
  const plansQuery = useQuery({
    queryKey: ["subscription-plans"],
    queryFn: () => MiscService.getSubscriptionPlans(),
  })

  // Current subscription from user data
  const currentSubscription = currentUser?.subscription

  const capitalizePlanName = (planName: string) => {
    return planName.charAt(0).toUpperCase() + planName.slice(1)
  }

  const formatPrice = (price: number, period: number) => {
    if (price === 0) return "Free"
    const monthlyPrice = price
    return period === 1
      ? `$${monthlyPrice}/month`
      : `$${monthlyPrice}/month (billed annually)`
  }

  if (plansQuery.isLoading) {
    return (
      <Container maxW="full">
        <Flex justify="center" align="center" height="200px">
          <Spinner size="lg" />
        </Flex>
      </Container>
    )
  }

  if (plansQuery.error) {
    return (
      <Container maxW="full">
        <Alert status="error">
          <AlertIcon />
          <AlertTitle>Error loading subscription plans</AlertTitle>
          <AlertDescription>
            Unable to load subscription information. Please try again later.
          </AlertDescription>
        </Alert>
      </Container>
    )
  }

  const plans = plansQuery.data || []
  const currentPlan =
    plans.find(
      (plan: SubscriptionPlan) => plan.name === currentSubscription?.plan_name,
    ) || plans.find((plan: SubscriptionPlan) => plan.name === "free")

  return (
    <>
      <Container maxW="full">
        <Heading size="md" py={4}>
          Subscription
        </Heading>
        {/* Current subscription status */}
        <Box mb={6}>
          <Stack spacing={2}>
            <Text>
              <Text as="span" fontWeight="semibold">
                Plan:{" "}
              </Text>
              {currentPlan?.name
                ? capitalizePlanName(currentPlan.name)
                : "Free"}
            </Text>

            <Text>
              <Text as="span" fontWeight="semibold">
                Price:{" "}
              </Text>
              {currentSubscription
                ? formatPrice(
                    currentSubscription.price,
                    currentSubscription.period_months,
                  )
                : "Free"}
            </Text>

            {currentSubscription && (
              <>
                <Text>
                  <Text as="span" fontWeight="semibold">
                    Paid until:{" "}
                  </Text>
                  {currentSubscription.paid_until
                    ? formatTimestamp(currentSubscription.paid_until)
                    : "N/A"}
                </Text>

                <Text>
                  <Text as="span" fontWeight="semibold">
                    Billing period:{" "}
                  </Text>
                  {currentSubscription.period_months === 1
                    ? "Monthly"
                    : "Annual"}
                </Text>
              </>
            )}

            <Text>
              <Text as="span" fontWeight="semibold">
                Private projects:{" "}
              </Text>
              {currentPlan?.private_projects_limit === null
                ? "Unlimited"
                : currentPlan?.private_projects_limit || "0"}
            </Text>

            <Text>
              <Text as="span" fontWeight="semibold">
                Storage limit:{" "}
              </Text>
              {currentPlan
                ? `${currentPlan.storage_limit.toFixed(0)} GB`
                : "N/A"}
            </Text>
          </Stack>

          {/* Change plan button */}
          <Button variant={"primary"} mt={4} onClick={onOpen} size="sm">
            Change plan
          </Button>
        </Box>
      </Container>

      {/* Subscription picker modal */}
      <Modal isOpen={isOpen} onClose={onClose} isCentered size="4xl">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Change subscription</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            <PickSubscription
              user={currentUser}
              onSuccess={onClose}
              showHeading={false}
            />
          </ModalBody>
        </ModalContent>
      </Modal>
    </>
  )
}

export default Subscription
