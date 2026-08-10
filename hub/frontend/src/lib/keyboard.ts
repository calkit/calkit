import type { KeyboardEvent } from "react"

// Site-wide: Cmd/Ctrl+Enter submits the surrounding input (e.g., posting a
// comment). Returns an onKeyDown handler that runs `submit` only on that combo,
// and no-ops otherwise so normal typing (including plain Enter) is unaffected.
export const submitOnCmdEnter = (submit: () => void) => (e: KeyboardEvent) => {
  if (e.key !== "Enter" || !(e.metaKey || e.ctrlKey)) return
  e.preventDefault()
  submit()
}
