import { Button, Container, Heading, Text } from "@chakra-ui/react"

import useCustomToast from "../../hooks/useCustomToast"
import useOnboardingFlags from "../../hooks/useOnboarding"

/**
 * Bring back checklists the user has hidden or ticked off by hand.
 *
 * Hiding a checklist is easy to do and, from the page it was on, there's
 * nothing left to click to undo it once the list is complete. This is where
 * that decision is reversible, and the count is shown so the button says
 * what it will actually do rather than being a leap of faith.
 */
const OnboardingChecklists = () => {
  const showToast = useCustomToast()
  const { flagsQuery, flagCount, resetAllMutation } = useOnboardingFlags()
  const reset = () =>
    resetAllMutation.mutate(undefined, {
      onSuccess: () =>
        showToast(
          "Checklists reset",
          "Your setup checklists are back on the home and project pages.",
          "success",
        ),
      onError: () =>
        showToast(
          "Something went wrong",
          "Could not reset your checklists. Try again.",
          "error",
        ),
    })
  return (
    <Container maxW="full">
      <Heading size="md" py={4}>
        Setup checklists
      </Heading>
      <Text mb={2}>
        The home page and each project page show what's left to set up. Steps
        tick off on their own as the work gets done, so resetting won't re-open
        anything you've actually finished.
      </Text>
      <Text mb={4} color="ui.dim" fontSize="sm">
        {flagsQuery.isPending
          ? "Checking…"
          : flagCount === 0
            ? "Nothing is hidden or marked off by hand right now."
            : `You've hidden or marked off ${flagCount} ${
                flagCount === 1 ? "item" : "items"
              }.`}
      </Text>
      <Button
        variant="primary"
        isDisabled={flagsQuery.isPending || flagCount === 0}
        isLoading={resetAllMutation.isPending}
        onClick={reset}
      >
        Reset my checklists
      </Button>
    </Container>
  )
}

export default OnboardingChecklists
