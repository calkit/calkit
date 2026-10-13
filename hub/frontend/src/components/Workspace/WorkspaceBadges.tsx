import { Badge } from "@chakra-ui/react"

import type { Workspace } from "../../client"
import Tooltip from "../Common/Tooltip"

// What a workspace's latest check-in says about it: its pipeline, whether
// another hub has it, and how it differs from its remote
export default function WorkspaceBadges({ ws }: { ws: Workspace }) {
  return (
    <>
      {ws.running ? (
        <Tooltip
          label={
            ws.running_since
              ? `Since ${new Date(ws.running_since).toLocaleString()}`
              : "Pipeline running"
          }
        >
          <Badge ml={2} colorScheme="blue" fontSize="2xs">
            running
            {ws.running_stages?.length
              ? ` ${ws.running_stages.join(", ")}`
              : ""}
          </Badge>
        </Tooltip>
      ) : ws.last_run ? (
        <Tooltip
          label={`Last run ${ws.last_run.status}${
            ws.last_run.ended
              ? ` ${new Date(ws.last_run.ended).toLocaleString()}`
              : ""
          }`}
        >
          <Badge
            ml={2}
            colorScheme={ws.last_run.status === "failed" ? "red" : "green"}
            fontSize="2xs"
          >
            {ws.last_run.status === "failed"
              ? `failed${
                  ws.last_run.failed_stages?.length
                    ? ` at ${ws.last_run.failed_stages.join(", ")}`
                    : ""
                }`
              : "last run ok"}
          </Badge>
        </Tooltip>
      ) : null}
      {ws.in_use_by && (
        <Tooltip
          label={`The Operator for ${ws.in_use_by} on this machine is using it, so this one can't until it's done`}
        >
          <Badge ml={2} colorScheme="orange" fontSize="2xs">
            in use from {ws.in_use_by.replace(/^https?:\/\//, "")}
          </Badge>
        </Tooltip>
      )}
      {ws.dirty && (
        <Badge ml={2} colorScheme="yellow" fontSize="2xs">
          uncommitted
        </Badge>
      )}
      {!!ws.ahead && (
        <Badge ml={2} fontSize="2xs">
          {ws.ahead} ahead
        </Badge>
      )}
      {!!ws.behind && (
        <Badge ml={2} fontSize="2xs">
          {ws.behind} behind
        </Badge>
      )}
    </>
  )
}
