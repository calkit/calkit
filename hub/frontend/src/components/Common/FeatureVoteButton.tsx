import { Button, HStack, Text, Tooltip } from "@chakra-ui/react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { FiThumbsUp } from "react-icons/fi"

import { FeedbackService } from "../../client"
import { isLoggedIn } from "../../hooks/useAuth"

interface FeatureVoteButtonProps {
  /** The feature key the hub knows, e.g. "local-workspace-compute". */
  feature: string
  label?: string
  votedLabel?: string
  size?: "xs" | "sm" | "md"
  /** Show the running tally next to the button; off where space is tight. */
  showCount?: boolean
}

/**
 * A vote for a feature that isn't built yet, with the running tally.
 *
 * One click casts, another withdraws; the count is what tells us whether
 * to build it, so it's shown rather than hidden.
 */
const FeatureVoteButton = ({
  feature,
  label = "I want this feature",
  votedLabel = "You want this feature",
  size = "sm",
  showCount = true,
}: FeatureVoteButtonProps) => {
  const queryClient = useQueryClient()
  const { data: status } = useQuery({
    queryKey: ["feature-votes", feature],
    queryFn: () =>
      FeedbackService.getFeatureVoteStatus({ feature }).then(
        (response) => response.data,
      ),
    enabled: isLoggedIn(),
  })
  const mutation = useMutation({
    mutationFn: (voted: boolean) =>
      voted
        ? FeedbackService.deleteFeatureVote({ feature }).then(
            (response) => response.data,
          )
        : FeedbackService.postFeatureVote({ feature }).then(
            (response) => response.data,
          ),
    onSuccess: (data) =>
      queryClient.setQueryData(["feature-votes", feature], data),
  })
  if (!isLoggedIn()) return null
  return (
    <HStack spacing={2}>
      <Tooltip
        label="Click to remove your vote"
        isDisabled={!status?.has_voted}
      >
        <Button
          type="button"
          size={size}
          variant={status?.has_voted ? "solid" : "outline"}
          colorScheme={status?.has_voted ? "green" : "gray"}
          leftIcon={<FiThumbsUp />}
          onClick={() => mutation.mutate(status?.has_voted ?? false)}
          isLoading={mutation.isPending}
          isDisabled={status == null}
        >
          {status?.has_voted ? votedLabel : label}
        </Button>
      </Tooltip>
      {showCount && status != null && (
        <Text fontSize="xs" color="gray.500">
          {status.count} {status.count === 1 ? "vote" : "votes"}
        </Text>
      )}
    </HStack>
  )
}

export default FeatureVoteButton
