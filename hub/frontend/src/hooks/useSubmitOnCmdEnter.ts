import { useEffect } from "react"

/** Whether a keydown is the "submit this form" chord: Cmd or Ctrl + Enter. */
export function isSubmitChord(e: {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
}): boolean {
  return (
    e.key === "Enter" && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey
  )
}

/**
 * Cmd+Enter (Ctrl+Enter elsewhere) submits the form the focused field is in.
 *
 * Plain Enter already submits from a single-line input, but a textarea
 * swallows it for a newline, and most of our forms end in one. One listener
 * at the root covers every form rather than each modal wiring its own.
 * `requestSubmit` runs the same validation and submit handler a click on
 * the button would, which is what makes this safe to do blindly.
 */
export default function useSubmitOnCmdEnter() {
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (!isSubmitChord(e)) return
      const target = e.target as HTMLElement | null
      const form = target?.closest?.("form")
      if (!form || !(form instanceof HTMLFormElement)) return
      // An editor or widget that handles the chord itself keeps it.
      if (e.defaultPrevented) return
      e.preventDefault()
      form.requestSubmit()
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [])
}
