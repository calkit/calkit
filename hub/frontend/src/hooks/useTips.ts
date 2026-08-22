import mixpanel from "mixpanel-browser"

import {
  activeTip,
  TIPS,
  TIPS_DISMISSED,
  TIPS_PROJECT_PREFIX,
  type TipId,
  tipDoneFlag,
  tipsProjectId,
} from "../lib/tips"
import useOnboardingFlags from "./useOnboarding"

/**
 * The first-project tips for a project: which one is up, and the ways
 * to move past it.
 *
 * Tips only show on the project they belong to (the user's first, or
 * wherever they were last reset), and only while the user can act on
 * them. Every step is an onboarding flag, so the state follows the user
 * rather than the browser.
 */
const useTips = (projectId?: string | null, canAct = true) => {
  const project = useOnboardingFlags(projectId)
  const account = useOnboardingFlags(null)
  const belongsHere =
    Boolean(projectId) &&
    tipsProjectId(
      account.accountFlags,
      project.flagsQuery.data?.first_project_id,
    ) === projectId
  const dismissed = project.projectFlags.includes(TIPS_DISMISSED)
  const tip =
    belongsHere && canAct && project.flagsQuery.data
      ? activeTip(project.projectFlags)
      : null
  const markDone = (id: TipId, how: "clicked" | "dismissed") => {
    mixpanel.track(
      how === "clicked" ? "Clicked onboarding tip" : "Dismissed onboarding tip",
      { tip: id },
    )
    project.setFlag(tipDoneFlag(id), true)
  }
  const dismissAll = () => {
    mixpanel.track("Dismissed onboarding tips", { source: "project-menu" })
    project.setFlag(TIPS_DISMISSED, true)
  }
  // Clears every tip flag on this project and pins tips to it, so they
  // come back here even when it isn't the first project. The writes run
  // in order: an old pin's delete landing after the new pin's create
  // would leave the project unpinned.
  const resetAll = async () => {
    mixpanel.track("Reset onboarding tips", { source: "project-menu" })
    await project.setFlagAsync(TIPS_DISMISSED, false)
    for (const t of TIPS) await project.setFlagAsync(tipDoneFlag(t.id), false)
    for (const flag of account.accountFlags) {
      if (flag.startsWith(TIPS_PROJECT_PREFIX)) {
        await account.setFlagAsync(flag, false)
      }
    }
    await account.setFlagAsync(`${TIPS_PROJECT_PREFIX}${projectId}`, true)
  }
  return {
    tip,
    /** Tips are on for this project and not hidden. */
    showing: belongsHere && !dismissed,
    markDone,
    dismissAll,
    resetAll,
  }
}

export default useTips
