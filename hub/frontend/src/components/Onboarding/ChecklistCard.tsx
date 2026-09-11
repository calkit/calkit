import { CheckCircleIcon } from "@chakra-ui/icons"
import {
  Box,
  Button,
  Collapse,
  Flex,
  Heading,
  Icon,
  Progress,
  SimpleGrid,
  Spacer,
  Text,
  useColorModeValue,
} from "@chakra-ui/react"
import mixpanel from "mixpanel-browser"
import type { ReactNode } from "react"
import { FiCircle } from "react-icons/fi"

import {
  type OnboardingStep,
  isComplete,
  progressPercent,
} from "../../lib/onboarding"
import Tooltip from "../Common/Tooltip"

/**
 * A step's status icon, which is also how a step gets ticked off.
 *
 * Clicking an empty circle is the obvious gesture on a checklist, so it's
 * the one that marks a step done. A step we detected as done has nothing to
 * undo -- un-marking it would leave it done and look broken -- so only a
 * mark the user made themselves is clickable in the other direction.
 */
function StepMark({
  step,
  onMarkDone,
}: {
  step: OnboardingStep
  onMarkDone?: (step: string, done: boolean) => void
}) {
  const canToggle =
    Boolean(onMarkDone) &&
    !step.detectedOnly &&
    (!step.done || step.manuallyDone)
  const icon = (
    <Icon
      as={step.done ? CheckCircleIcon : FiCircle}
      color={step.done ? "ui.success" : "ui.dim"}
      mt={1}
      flexShrink={0}
      aria-hidden
    />
  )
  if (!canToggle) {
    return icon
  }
  return (
    <Tooltip label={step.done ? "Not done after all?" : "Mark as done"}>
      <Box
        as="button"
        type="button"
        aria-label={
          step.done
            ? `Mark "${step.title}" as not done`
            : `Mark "${step.title}" as done`
        }
        lineHeight={0}
        onClick={() => {
          mixpanel.track("Toggled onboarding step", {
            step: step.key,
            done: !step.done,
          })
          onMarkDone?.(step.key, !step.done)
        }}
        _hover={{ opacity: 0.6 }}
      >
        {icon}
      </Box>
    </Tooltip>
  )
}

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
  /**
   * Columns to lay the steps out in on a wide screen. Two suits a card that
   * spans the page and a list whose steps can be done in any order; one
   * suits a narrow column and a sequence that has to happen in order.
   */
  columns?: number
}

/**
 * A checklist whose items are facts about the project, not stored progress.
 *
 * Steps stay visible after they're done rather than disappearing, since the
 * finished ones are what make the remaining ones feel finishable.
 *
 * The steps stay listed once everything is done, since "what did this
 * check?" is a fair question to ask of a checklist that has finished.
 * Dismissing hides it entirely; the project menu and the settings page are
 * how it comes back, so a misclick isn't permanent.
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
  columns = 1,
}: ChecklistCardProps) => {
  const secBgColor = useColorModeValue("ui.secondary", "ui.darkSlate")
  const dividerColor = useColorModeValue("gray.200", "gray.600")
  const complete = isComplete(steps)
  const percent = progressPercent(steps)
  const remaining = steps.filter((step) => !step.done).length
  // Dismissing removes it outright rather than leaving a stub: the project
  // menu brings it back, and the settings page resets every checklist, so
  // there's a way back that doesn't cost a strip on the page forever.
  if (dismissed) {
    return null
  }
  return (
    <Box py={4} px={6} mb={4} borderRadius="lg" bg={secBgColor}>
      <Flex align="center" mb={1}>
        <Heading size="md">{title}</Heading>
        <Spacer />
        <Button
          size="xs"
          variant="ghost"
          onClick={() => {
            mixpanel.track("Dismissed onboarding checklist", {
              title,
              remaining,
              complete,
            })
            onDismissedChange(true)
          }}
        >
          Dismiss
        </Button>
      </Flex>
      {complete ? (
        <Flex align="center" gap={2} mt={2} mb={4}>
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
        </>
      )}
      <SimpleGrid
        columns={{ base: 1, md: columns }}
        spacingX={10}
        spacingY={columns > 1 ? 5 : 0}
      >
        {steps.map((step, index) => (
          <Box
            key={step.key}
            // In a grid the top border would run across unrelated
            // steps, so those rows are separated by spacing instead.
            pt={columns > 1 || index === 0 ? 0 : 3}
            mt={columns > 1 || index === 0 ? 0 : 3}
            borderTopWidth={columns > 1 || index === 0 ? 0 : 1}
            borderColor={dividerColor}
          >
            <Flex align="flex-start" gap={2}>
              <StepMark step={step} onMarkDone={onMarkDone} />
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
                </Collapse>
              </Box>
            </Flex>
          </Box>
        ))}
      </SimpleGrid>
    </Box>
  )
}

export default ChecklistCard
