/**
 * Keeping password managers from filling in fields that aren't a person's
 * name, email, or password. See the hub's AGENTS.md for what else Dashlane
 * needs.
 */

// Spread onto each input, since Dashlane ignores a form-level opt-out
export const noAutofill = {
  autoComplete: "off",
  "data-form-type": "other",
  "data-1p-ignore": true,
  "data-lpignore": "true",
  "data-bwignore": true,
} as const

// Masks a text input like a password field, which password managers take
// for an account's password whatever its attributes say
export const maskedText = { WebkitTextSecurity: "disc" } as const
