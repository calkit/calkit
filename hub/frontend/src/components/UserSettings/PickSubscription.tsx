import {
  Box,
  Button,
  Card,
  CardBody,
  CardFooter,
  CardHeader,
  Flex,
  Heading,
  IconButton,
  Input,
  Link,
  NumberDecrementStepper,
  NumberIncrementStepper,
  NumberInput,
  NumberInputField,
  NumberInputStepper,
  SimpleGrid,
  Spinner,
  Switch,
  Text,
  UnorderedList,
  ListItem,
  useBoolean,
  Alert,
  AlertIcon,
  AlertTitle,
  AlertDescription,
  Modal,
  ModalOverlay,
  ModalContent,
  ModalHeader,
  ModalFooter,
  ModalBody,
  ModalCloseButton,
  useDisclosure,
} from "@chakra-ui/react"
import { MdCancel, MdCheck } from "react-icons/md"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { useNavigate } from "@tanstack/react-router"

import {
  type ApiError,
  type SubscriptionUpdate,
  type OrgSubscriptionUpdate,
  type SubscriptionPlan,
  type UserPublic,
  UsersService,
  MiscService,
  OrgsService,
} from "../../client"
import useCustomToast from "../../hooks/useCustomToast"
import { capitalizeFirstLetter } from "../../lib/strings"
import { handleError } from "../../lib/errors"
import mixpanel from "mixpanel-browser"

interface PickSubscriptionProps {
  user?: UserPublic | null
  onSuccess?: () => void
  showHeading?: boolean
  containerProps?: any
}

const PickSubscription = ({
  user,
  onSuccess,
  showHeading = true,
  containerProps = {},
}: PickSubscriptionProps) => {
  const [annual, setAnnual] = useBoolean(false)
  const [team, setTeam] = useBoolean(false)
  const [discountCodeVisible, setDiscountCodeVisible] = useBoolean(false)
  const [teamSize, setTeamSize] = useState(5)
  const [orgName, setOrgName] = useState("")
  const navigate = useNavigate()

  const plansQuery = useQuery({
    queryKey: ["subscription-plans"],
    queryFn: () => MiscService.getSubscriptionPlans(),
  })

  const preferredPlanName = "standard"

  const getPriceUnits = () => {
    if (team) {
      return "/user/mo"
    }
    return "/mo"
  }

  const getPlans = () => {
    if (plansQuery.error || !plansQuery.data) {
      return []
    }
    const plans = plansQuery.data
    if (team && plans) {
      return plans.filter((plan) => plan.name !== "free")
    }
    return plans
  }

  const [discountCode, setDiscountCode] = useState<string>("")
  const [discountQueryEnabled, setDiscountQueryEnabled] = useBoolean(false)
  const { isOpen, onOpen, onClose } = useDisclosure()
  const [pendingPlan, setPendingPlan] = useState<string | null>(null)

  // Define plan hierarchy for downgrade detection
  const planHierarchy = { free: 0, standard: 1, professional: 2 }

  const isCurrentPlanAndPeriod = (planName: string) => {
    if (!user?.subscription?.plan_name) return false
    const isSamePlan = user.subscription.plan_name === planName.toLowerCase()
    const currentPeriod =
      user.subscription.period_months === 12 ? "annual" : "monthly"
    const selectedPeriod = annual ? "annual" : "monthly"
    return isSamePlan && currentPeriod === selectedPeriod
  }

  const getButtonText = (planName: string) => {
    if (isCurrentPlanAndPeriod(planName)) {
      return "Current plan"
    }

    if (user?.subscription?.plan_name) {
      const currentPlanValue =
        planHierarchy[
          user.subscription.plan_name as keyof typeof planHierarchy
        ] ?? 0
      const newPlanValue =
        planHierarchy[planName as keyof typeof planHierarchy] ?? 0

      if (newPlanValue > currentPlanValue) {
        return "Upgrade"
      } else if (newPlanValue < currentPlanValue) {
        return "Downgrade"
      } else {
        // Same plan level, different period
        const currentPeriod =
          user.subscription.period_months === 12 ? "annual" : "monthly"
        const selectedPeriod = annual ? "annual" : "monthly"
        if (currentPeriod !== selectedPeriod) {
          return `Switch to ${selectedPeriod}`
        }
      }
    }

    return `${planName === preferredPlanName ? "🚀 " : ""}Let's go!`
  }

  const isDowngrade = (newPlanName: string) => {
    if (!user?.subscription?.plan_name) return false
    const currentPlanValue =
      planHierarchy[
        user.subscription.plan_name as keyof typeof planHierarchy
      ] ?? 0
    const newPlanValue =
      planHierarchy[newPlanName as keyof typeof planHierarchy] ?? 0
    return newPlanValue < currentPlanValue
  }

  const discountCodeCheckQuery = useQuery({
    queryKey: ["discount-codes", discountCode, team, teamSize],
    queryFn: () =>
      MiscService.getDiscountCode({
        discountCode,
        nUsers: team ? teamSize : 1,
      }),
    enabled:
      Boolean(discountCode) && discountQueryEnabled && discountCodeVisible,
    retry: 1,
  })

  const queryClient = useQueryClient()

  const calcPrice = (plan: SubscriptionPlan) => {
    const planName = plan.name
    const price = plan.price
    const annualDiscount = plan.annual_discount_factor
    const discountedPrice = discountCodeCheckQuery.data?.price
    const discountedPlanName = discountCodeCheckQuery.data?.plan_name
    if (planName.toLowerCase() === discountedPlanName) {
      return discountedPrice
    }
    if (!price) {
      return price
    }
    if (annual && annualDiscount) {
      return price * annualDiscount
    }
    return price
  }

  const showToast = useCustomToast()

  const subscriptionMutation = useMutation({
    mutationFn: (data: SubscriptionUpdate | OrgSubscriptionUpdate) => {
      mixpanel.track("Clicked subscription option", {
        team: team,
        plan_name: data.plan_name,
        period: data.period,
      })
      if (team && "n_users" in data) {
        return OrgsService.putOrgSubscription({ requestBody: data, orgName })
      }
      return UsersService.putUserSubscription({ requestBody: data })
    },
    onSuccess: (data) => {
      if (onSuccess) {
        onSuccess()
      }

      if (data.stripe_session_client_secret) {
        // Don't refetch queries when redirecting to checkout
        // The user data will be updated after payment processing
        navigate({
          to: "/checkout",
          search: { client_secret: data.stripe_session_client_secret },
        })
      } else {
        // Only refetch user data when NOT going to checkout
        queryClient.refetchQueries({ queryKey: ["currentUser"] })
        queryClient.refetchQueries({ queryKey: ["users", "me"] })
      }
    },
    onError: (err: ApiError) => {
      handleError(err, showToast)
    },
  })

  type PlanName = "free" | "standard" | "professional"

  const handlePlanClick = (planName: string) => {
    if (isDowngrade(planName)) {
      setPendingPlan(planName)
      onOpen()
    } else {
      handleSubmit(planName)
    }
  }

  const handleConfirmedSubmit = () => {
    if (pendingPlan) {
      handleSubmit(pendingPlan)
      setPendingPlan(null)
      onClose()
    }
  }

  const handleSubmit = (planName: string) => {
    if (!team) {
      subscriptionMutation.mutate({
        plan_name: planName as PlanName,
        period: annual ? "annual" : "monthly",
        discount_code: discountCode ? discountCode : null,
      })
    } else {
      subscriptionMutation.mutate({
        plan_name: planName as PlanName,
        period: annual ? "annual" : "monthly",
        discount_code: discountCode ? discountCode : null,
        n_users: teamSize,
      } as OrgSubscriptionUpdate)
    }
  }

  if (plansQuery.isLoading) {
    return (
      <Flex justify="center" align="center" height="200px" width="full">
        <Spinner size="lg" />
      </Flex>
    )
  }

  if (plansQuery.error) {
    return (
      <Alert status="error">
        <AlertIcon />
        <AlertTitle>Error loading subscription plans</AlertTitle>
        <AlertDescription>
          Unable to load subscription information. Please try again later.
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <Box {...containerProps}>
      <Box>
        {showHeading && (
          <Flex justify={"center"}>
            <Heading size="lg" mb={4}>
              Choose your plan
              {user?.github_username ? `, ${user.github_username}` : ""}:
            </Heading>
          </Flex>
        )}

        <Flex mb={4} align={"center"} justify={"center"} alignItems={"center"}>
          <Text mr={1}>Monthly</Text>
          <Switch
            isChecked={annual}
            onChange={setAnnual.toggle}
            mr={1}
            colorScheme="green"
          />
          <Text mr={6}>Annual</Text>
          <Text mr={1}>Individual</Text>
          <Switch
            mr={1}
            isChecked={team}
            onChange={setTeam.toggle}
            colorScheme="blue"
          />
          <Text>Team</Text>
        </Flex>

        {team ? (
          <Flex mb={4} justify={"center"} align={"center"}>
            <Text mr={2}>GitHub org name:</Text>
            <Input
              width="150px"
              placeholder="Ex: my-lab"
              mr={2}
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
            />
            <Text mr={2}>Team size:</Text>
            <NumberInput
              defaultValue={5}
              min={2}
              max={50}
              width={"75px"}
              value={teamSize}
              onChange={(valueString) => setTeamSize(Number(valueString))}
            >
              <NumberInputField />
              <NumberInputStepper>
                <NumberIncrementStepper />
                <NumberDecrementStepper />
              </NumberInputStepper>
            </NumberInput>
          </Flex>
        ) : (
          ""
        )}

        <Box mb={4}>
          <SimpleGrid spacing={4} columns={team ? 2 : 3}>
            {/* Cards for each plan */}
            {getPlans().map((plan) => (
              <Card
                align={"center"}
                key={plan.name}
                borderWidth={plan.name === preferredPlanName ? 2 : 0}
                borderColor={"green.500"}
              >
                <CardHeader>
                  <Heading size="md">
                    {capitalizeFirstLetter(plan.name)}
                    {plan.price
                      ? `: $${calcPrice(plan)}${getPriceUnits()}`
                      : ""}
                  </Heading>
                </CardHeader>
                <CardBody>
                  <UnorderedList>
                    <ListItem>Unlimited collaborators</ListItem>
                    <ListItem>Unlimited public projects</ListItem>
                    <ListItem>
                      {plan.private_projects_limit
                        ? plan.private_projects_limit
                        : "Unlimited"}{" "}
                      private project
                      {plan.private_projects_limit === null ||
                      (typeof plan.private_projects_limit === "number" &&
                        plan.private_projects_limit > 1)
                        ? "s"
                        : ""}
                      {team ? "/user" : ""}
                    </ListItem>
                    <ListItem>
                      {plan.storage_limit} GB storage{team ? "/user" : ""}
                    </ListItem>
                  </UnorderedList>
                </CardBody>
                <CardFooter>
                  <Button
                    variant={
                      plan.name === preferredPlanName ? "primary" : undefined
                    }
                    isLoading={subscriptionMutation.isPending}
                    onClick={() => handlePlanClick(plan.name.toLowerCase())}
                    isDisabled={
                      (team && !orgName) || isCurrentPlanAndPeriod(plan.name)
                    }
                  >
                    {getButtonText(plan.name)}
                  </Button>
                </CardFooter>
              </Card>
            ))}
          </SimpleGrid>
        </Box>

        <Flex justifyItems={"center"} justifyContent="center" width={"100%"}>
          <Box>
            <Box textAlign={"center"}>
              {discountCodeVisible ? (
                <>
                  <Flex align={"center"}>
                    <Input
                      value={discountCode}
                      onChange={({ target }) => setDiscountCode(target.value)}
                      placeholder="Enter discount code here"
                      isDisabled={
                        discountCodeCheckQuery.isLoading ||
                        discountCodeCheckQuery.data?.is_valid
                      }
                    />
                    <IconButton
                      aria-label="apply"
                      icon={<MdCheck />}
                      bg="none"
                      size={"s"}
                      p={1}
                      mx={1}
                      isDisabled={
                        !discountCode || discountCodeCheckQuery.data?.is_valid
                      }
                      isLoading={discountCodeCheckQuery.isLoading}
                      onClick={() => setDiscountQueryEnabled.on()}
                    />
                    <IconButton
                      aria-label="cancel"
                      icon={<MdCancel />}
                      bg="none"
                      size={"s"}
                      onClick={() => {
                        setDiscountCodeVisible.toggle()
                        setDiscountQueryEnabled.off()
                        queryClient.resetQueries({
                          queryKey: ["discount-codes"],
                        })
                        setDiscountCode("")
                      }}
                    />
                  </Flex>
                  {discountCodeCheckQuery.error ? (
                    <Text mt={1} color={"red"} fontSize="sm">
                      Discount code invalid.
                    </Text>
                  ) : (
                    ""
                  )}
                  {discountCodeCheckQuery.data?.is_valid ? (
                    <Text mt={1} color={"green.500"} fontSize="sm">
                      Discount code applied! (
                      {discountCodeCheckQuery.data.n_users} user
                      {discountCodeCheckQuery.data.n_users &&
                      discountCodeCheckQuery.data.n_users > 1
                        ? "s"
                        : ""}{" "}
                      for {discountCodeCheckQuery.data.months} months @ $
                      {discountCodeCheckQuery.data.price}/mo)
                    </Text>
                  ) : (
                    <>
                      {discountCodeCheckQuery.data?.reason ? (
                        <Text mt={1} color={"red"} fontSize="sm">
                          Discount code invalid.{" "}
                          {discountCodeCheckQuery.data?.reason}
                        </Text>
                      ) : (
                        ""
                      )}
                    </>
                  )}
                </>
              ) : (
                <Link onClick={setDiscountCodeVisible.toggle}>
                  <Text>Have a discount code? Click here.</Text>
                </Link>
              )}
            </Box>
            <Box mt={2} textAlign={"center"}>
              <Link
                href="mailto:sales@calkit.io?subject=Calkit enterprise license"
                isExternal
              >
                <Text fontSize="sm">
                  Looking for enterprise, on prem? Email us.
                </Text>
              </Link>
            </Box>
          </Box>
        </Flex>
      </Box>

      {/* Downgrade confirmation modal */}
      <Modal isOpen={isOpen} onClose={onClose} isCentered>
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>Confirm downgrade</ModalHeader>
          <ModalCloseButton />
          <ModalBody>
            <Text>
              You're about to downgrade your subscription. This may result in:
            </Text>
            <UnorderedList mt={2} mb={4}>
              <ListItem>Loss of access to some features</ListItem>
              <ListItem>Reduced storage limits</ListItem>
              <ListItem>Fewer private projects allowed</ListItem>
            </UnorderedList>
            <Text>Are you sure you want to continue?</Text>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" mr={3} onClick={onClose}>
              Cancel
            </Button>
            <Button
              colorScheme="red"
              onClick={handleConfirmedSubmit}
              isLoading={subscriptionMutation.isPending}
            >
              Confirm downgrade
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
    </Box>
  )
}

export default PickSubscription
