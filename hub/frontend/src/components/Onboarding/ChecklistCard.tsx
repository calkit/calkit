import { CheckCircleIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Collapse,
  Flex,
  Heading,
  Icon,
  Link,
  Progress,
  Spacer,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import type { ReactNode } from "react"
import { FiCircle } from "react-icons/fi"

import {
  type OnboardingStep,
  isComplete,
  progressPercent,
} from "../../lib/onboarding"

interface ChecklistCardProps {
  title: string
  /** One line under the heading saying what finishing the list buys. */
  intro?: ReactNode
  steps: OnboardingStep[]
  /** What to render under a step that isn't done yet, keyed by step key. */
  actions?: Record<string, ReactNode>
  /** Mark a step done by hand, or take the mark back. */
  onMarkDone?: (step: string, done: boolean) => void
  /** Whether the user has put this list away. */
  dismissed: boolean
  onDismissedChange: (dismissed: boolean) => void
  /** Shown in place of the list once nothing required is left. */
  doneMessage: string
}

/**
 * A checklist whose items are facts about the project, not stored progress.
 *
 * Steps stay visible after they're done rather than disappearing, since the
 * finished ones are what make the remaining ones feel finishable.
 *
 * Hiding a list that still has work left collapses it to a single line
 * rather than removing it: a card that vanishes with no way back turns one
 * misclick into a permanently missing path through the product. Once
 * nothing required is left, dismissing does remove it for good, which is
 * what "I'm finished with this" should mean.
 */
const ChecklistCard = ({
  title,
  intro,
  steps,
  actions,
  onMarkDone,
  dismissed,
  onDismissedChange,
  doneMessage,
}: ChecklistCardProps) => {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const dividerColor = useColorModeValue("gray.200", "gray.600")
  const complete = isComplete(steps)
  const percent = progressPercent(steps)
  const remaining = steps.filter((step) => !step.done).length
  if (dismissed) {
    if (complete) {
      return null
    }
    return (
      <Flex
        align="center"
        py={2}
        px={6}
        mb={4}
        borderRadius="lg"
        bg={secBgColor}
      >
        <Text fontSize="sm" color="ui.dim">
          {title} — {remaining} left
        </Text>
        <Spacer />
        <Button
          size="xs"
          variant="ghost"
          onClick={() => onDismissedChange(false)}
        >
          Show
        </Button>
      </Flex>
    )
  }
  return (
    <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
      <Flex align="center" mb={1}>
        <Heading size="md">{title}</Heading>
        <Spacer />
        <Button
          size="xs"
          variant="ghost"
          onClick={() => onDismissedChange(true)}
        >
          {complete ? "Dismiss" : "Hide"}
        </Button>
      </Flex>
      {complete ? (
        <Flex align="center" gap={2} mt={2}>
          <Icon as={CheckCircleIcon} color="ui.success" />
          <Text fontSize="sm">{doneMessage}</Text>
        </Flex>
      ) : (
        <>
          {intro ? (
            <Text fontSize="sm" color="ui.dim" mb={3}>
              {intro}
            </Text>
          ) : null}
          <Flex align="center" gap={3} mb={4}>
            <Progress
              value={percent}
              size="sm"
              colorScheme="teal"
              borderRadius="full"
              flex="1"
            />
            <Text fontSize="xs" color="ui.dim" whiteSpace="nowrap">
              {remaining} left
            </Text>
          </Flex>
          {steps.map((step, index) => (
            <Box
              key={step.key}
              pt={index === 0 ? 0 : 3}
              mt={index === 0 ? 0 : 3}
              borderTopWidth={index === 0 ? 0 : 1}
              borderColor={dividerColor}
            >
              <Flex align="flex-start" gap={2}>
                <Icon
                  as={step.done ? CheckCircleIcon : FiCircle}
                  color={step.done ? "ui.success" : "ui.dim"}
                  mt={1}
                  flexShrink={0}
                />
                <Box flex="1">
                  <Flex align="center" gap={2}>
                    <Text
                      fontWeight={step.done ? "normal" : "semibold"}
                      color={step.done ? "ui.dim" : "inherit"}
                    >
                      {step.title}
                    </Text>
                    {step.optional && !step.done ? (
                      <Text fontSize="xs" color="ui.dim">
                        optional
                      </Text>
                    ) : null}
                  </Flex>
                  <Collapse in={!step.done} animateOpacity>
                    <Text fontSize="sm" color="ui.dim" mt={0.5}>
                      {step.detail}
                    </Text>
                    {actions?.[step.key] ? (
                      <Box mt={2}>{actions[step.key]}</Box>
                    ) : null}
                    {onMarkDone ? (
                      <Link
                        fontSize="xs"
                        color="ui.dim"
                        mt={2}
                        display="inline-block"
                        onClick={() => onMarkDone(step.key, true)}
                      >
                        Already done this? Mark it off
                      </Link>
                    ) : null}
                  </Collapse>
                </Box>
              </Flex>
            </Box>
          ))}
        </>
      )}
    </Box>
  )
}

export default ChecklistCard
