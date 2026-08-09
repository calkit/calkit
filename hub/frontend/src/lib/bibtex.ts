// Helpers for displaying BibTeX field values, which carry LaTeX markup that
// should not be shown raw (protective braces, accent macros, dashes).

// Accent and symbol macros mapped to their Unicode equivalents. Keys are the
// macro body as it appears after a backslash, e.g. `"o` for \"o (o-umlaut).
const LATEX_REPLACEMENTS: Record<string, string> = {
  '"a': "ä",
  '"o': "ö",
  '"u': "ü",
  '"A': "Ä",
  '"O': "Ö",
  '"U': "Ü",
  "'a": "á",
  "'e": "é",
  "'i": "í",
  "'o": "ó",
  "'u": "ú",
  "'n": "ń",
  "'c": "ć",
  "`a": "à",
  "`e": "è",
  "`i": "ì",
  "`o": "ò",
  "`u": "ù",
  "^a": "â",
  "^e": "ê",
  "^i": "î",
  "^o": "ô",
  "^u": "û",
  "~n": "ñ",
  "~a": "ã",
  "~o": "õ",
  "c c": "ç",
  "c C": "Ç",
  ss: "ß",
  o: "ø",
  O: "Ø",
  aa: "å",
  AA: "Å",
  ae: "æ",
  AE: "Æ",
}

// AAS/astronomy journal abbreviation macros (e.g. \apjl), which are defined by
// AASTeX but appear raw in BibTeX. Expand to the journal name.
const JOURNAL_MACROS: Record<string, string> = {
  aj: "Astronomical Journal",
  araa: "Annual Review of Astronomy and Astrophysics",
  apj: "Astrophysical Journal",
  apjl: "Astrophysical Journal Letters",
  apjs: "Astrophysical Journal Supplement",
  aap: "Astronomy and Astrophysics",
  aapr: "Astronomy and Astrophysics Reviews",
  aaps: "Astronomy and Astrophysics Supplement",
  mnras: "Monthly Notices of the Royal Astronomical Society",
  pasp: "Publications of the Astronomical Society of the Pacific",
  pasj: "Publications of the Astronomical Society of Japan",
  nat: "Nature",
  science: "Science",
  prd: "Physical Review D",
  prl: "Physical Review Letters",
  jgr: "Journal of Geophysical Research",
  grl: "Geophysical Research Letters",
  icarus: "Icarus",
  solphys: "Solar Physics",
  ssr: "Space Science Reviews",
  physrep: "Physics Reports",
}

// Convert a BibTeX/LaTeX field value into plain text suitable for display.
export const cleanLatex = (input: string): string => {
  let out = input
  // Links: \href{url}{text} shows the text, \url{url} shows the url. Do this
  // before brace-stripping, which would otherwise yield "\urlhttp://…".
  out = out.replace(/\\href\{([^{}]*)\}\{([^{}]*)\}/g, "$2")
  out = out.replace(/\\url\{([^{}]*)\}/g, "$1")
  // Accent and symbol macros in either brace form: {\"o} or \"o or \ss.
  for (const [macro, replacement] of Object.entries(LATEX_REPLACEMENTS)) {
    const body = macro.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    // Word macros like \ss or \o need a boundary so \other isn't matched;
    // symbol accents like \"o apply to the next letter, which follows directly.
    const boundary = /^[a-zA-Z]/.test(macro) ? "(?![a-zA-Z])" : ""
    out = out.replace(
      new RegExp(`\\{\\\\${body}\\}|\\\\${body}${boundary}`, "g"),
      replacement,
    )
    out = out.replace(new RegExp(`\\\\${body}\\{\\}`, "g"), replacement)
  }
  // Text-formatting wrappers: keep the content, drop the command.
  out = out.replace(
    /\\(?:textbf|textit|textsc|emph|texttt|mathrm|mathit|text)\{([^{}]*)\}/g,
    "$1",
  )
  // Journal abbreviation macros: \apjl -> its name.
  for (const [macro, name] of Object.entries(JOURNAL_MACROS)) {
    out = out.replace(new RegExp(`\\\\${macro}(?![a-zA-Z])`, "g"), name)
  }
  // A literal backslash, however it's encoded (Zotero exports one as
  // \textbackslash, which can round-trip into \textbackslash{} etc.).
  out = out.replace(/\\textbackslash\s*(?:\{\})?/g, "\\")
  // Escaped punctuation, including braces: \{ \} \& \% \_ \# \$. Unescaping
  // braces first means an escaped protective brace (\{2D\}, from a Zotero
  // round-trip) collapses to "2D" instead of leaving a stray backslash.
  out = out.replace(/\\([&%_#${}])/g, "$1")
  // Spacing macros (\, \; \: \ ) become a plain space.
  out = out.replace(/\\[,;: ]/g, " ")
  // Any remaining unknown control words (\foo) are dropped, keeping the text
  // around them. TeX swallows one trailing space after a control word.
  out = out.replace(/\\[a-zA-Z]+ ?/g, "")
  // Dashes and non-breaking spaces.
  out = out.replace(/---/g, "—").replace(/--/g, "–").replace(/~/g, " ")
  // Any remaining protective braces.
  out = out.replace(/[{}]/g, "")
  // Collapse whitespace left behind.
  return out.replace(/\s+/g, " ").trim()
}

// Format a BibTeX field value for display, dispatching on the field name: the
// `file` field is JabRef metadata, everything else is LaTeX-ish text.
export const formatBibField = (key: string, value: string): string =>
  key.toLowerCase() === "file" ? formatJabrefFile(value) : cleanLatex(value)

// JabRef stores the `file` field as `description:path:type` entries (multiple
// separated by `;`), with `\` , `:` and `;` backslash-escaped inside. Show just
// the file name(s) rather than the raw metadata.
export const formatJabrefFile = (value: string): string => {
  return value
    .split(/(?<!\\);/)
    .map((entry) => {
      // Split on unescaped colons; the path is the middle segment.
      const parts = entry.split(/(?<!\\):/)
      const path = parts.length >= 3 ? parts.slice(1, -1).join(":") : entry
      const unescaped = path
        .replace(/\\\\/g, "\\")
        .replace(/\\:/g, ":")
        .replace(/\\;/g, ";")
      const base = unescaped.split(/[/\\]/).pop() ?? unescaped
      return base.trim()
    })
    .filter(Boolean)
    .join(", ")
}
