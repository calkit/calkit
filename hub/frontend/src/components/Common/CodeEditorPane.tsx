// The CodeMirror editor shared by the app's editors (LaTeX source, arbitrary
// project files, and pipeline stages). Owns its document once mounted, so
// callers change files by remounting it with a different `key`.
import { Box } from "@chakra-ui/react"
import {
  HighlightStyle,
  StreamLanguage,
  syntaxHighlighting,
} from "@codemirror/language"
import { javascript, json } from "@codemirror/legacy-modes/mode/javascript"
import { julia } from "@codemirror/legacy-modes/mode/julia"
import { properties } from "@codemirror/legacy-modes/mode/properties"
import { python } from "@codemirror/legacy-modes/mode/python"
import { r } from "@codemirror/legacy-modes/mode/r"
import { shell } from "@codemirror/legacy-modes/mode/shell"
import { stex } from "@codemirror/legacy-modes/mode/stex"
import { toml } from "@codemirror/legacy-modes/mode/toml"
import { yaml } from "@codemirror/legacy-modes/mode/yaml"
import { Prec } from "@codemirror/state"
import { oneDarkTheme } from "@codemirror/theme-one-dark"
import { keymap } from "@codemirror/view"
import { tags as t } from "@lezer/highlight"
import { EditorView, basicSetup } from "codemirror"
import { type MutableRefObject, useEffect, useRef } from "react"

// Atom One Dark, matching the palette react-syntax-highlighter uses to *view*
// source elsewhere in the app, so a file looks the same being edited as being
// read. CodeMirror ships its own One Dark, but it assigns the colors to
// different tokens — LaTeX in particular came out mostly uncolored — so only
// its editor chrome (background, gutters, selection) is reused here, and the
// token colors below are taken from the highlight.js theme.
const ATOM_ONE_DARK = {
  gray: "#5c6370",
  red: "#e06c75",
  green: "#98c379",
  yellow: "#e6c07b",
  orange: "#d19a66",
  blue: "#61aeee",
  purple: "#c678dd",
  cyan: "#56b6c2",
}

const atomOneDarkHighlightStyle = HighlightStyle.define([
  { tag: t.comment, color: ATOM_ONE_DARK.gray, fontStyle: "italic" },
  // A LaTeX \command is the "keyword" of a document, and highlight.js colors
  // it like one; the stream parser reports it as a tag.
  {
    tag: [t.keyword, t.tagName, t.moduleKeyword, t.controlKeyword],
    color: ATOM_ONE_DARK.purple,
  },
  {
    tag: [t.string, t.regexp, t.inserted, t.special(t.string)],
    color: ATOM_ONE_DARK.green,
  },
  { tag: [t.atom, t.bool, t.null], color: ATOM_ONE_DARK.cyan },
  {
    // YAML keys arrive as definition(variableName).
    tag: [
      t.definition(t.variableName),
      t.attributeName,
      t.propertyName,
      t.typeName,
      t.number,
    ],
    color: ATOM_ONE_DARK.orange,
  },
  {
    tag: [t.className, t.standard(t.variableName)],
    color: ATOM_ONE_DARK.yellow,
  },
  {
    tag: [t.function(t.variableName), t.labelName, t.link, t.meta],
    color: ATOM_ONE_DARK.blue,
  },
  { tag: t.heading, color: ATOM_ONE_DARK.red, fontWeight: "bold" },
  { tag: [t.deleted, t.invalid], color: ATOM_ONE_DARK.red },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strong, fontWeight: "bold" },
])

// A CodeMirror mode for a file's extension, or none for plain text. Only the
// languages a Calkit project actually holds are wired up; anything else still
// edits fine, just without highlighting.
export function languageExtension(path: string) {
  const name = path.toLowerCase().split("/").pop() ?? ""
  const mode = name.endsWith(".py")
    ? python
    : name.endsWith(".yaml") || name.endsWith(".yml") || name === "dvc.lock"
      ? yaml
      : name.endsWith(".json")
        ? json
        : name.endsWith(".js") || name.endsWith(".ts")
          ? javascript
          : name.endsWith(".sh") || name.endsWith(".bash")
            ? shell
            : name.endsWith(".r")
              ? r
              : name.endsWith(".jl")
                ? julia
                : name.endsWith(".toml")
                  ? toml
                  : name.endsWith(".ini") || name.endsWith(".cfg")
                    ? properties
                    : name.endsWith(".tex") ||
                        name.endsWith(".cls") ||
                        name.endsWith(".sty") ||
                        name.endsWith(".bib")
                      ? stex
                      : null
  return mode ? [StreamLanguage.define(mode)] : []
}

interface CodeEditorPaneProps {
  initialDoc: string
  // Drives syntax highlighting. Pass a bare name (e.g. "stage.yaml") when the
  // content isn't a real file.
  path: string
  viewRef: MutableRefObject<EditorView | null>
  onChange: (text: string) => void
  // Cmd/Ctrl+Enter, when the caller has a "run" for it. CodeMirror's
  // default binding inserts a blank line, which is wrong in an editor whose
  // surroundings treat the chord as "go".
  onModEnter?: () => void
}

const CodeEditorPane = ({
  initialDoc,
  path,
  viewRef,
  onChange,
  onModEnter,
}: CodeEditorPaneProps) => {
  const ref = useRef<HTMLDivElement>(null)
  const onModEnterRef = useRef(onModEnter)
  onModEnterRef.current = onModEnter
  // The listener below is built once and would otherwise close over the first
  // render's onChange, so callbacks reading state (e.g. an auto-compile
  // toggle) would keep seeing that render's values. Go through a ref instead.
  const onChangeRef = useRef(onChange)
  onChangeRef.current = onChange
  // The view owns the document once created, so re-running this would discard
  // the user's edits. Callers remount (via key) to load different content.
  // biome-ignore lint/correctness/useExhaustiveDependencies: mount-only by design
  useEffect(() => {
    if (!ref.current) {
      return
    }
    const view = new EditorView({
      doc: initialDoc,
      extensions: [
        // Ahead of basicSetup's keymap so it wins over insertBlankLine.
        Prec.highest(
          keymap.of([
            {
              key: "Mod-Enter",
              run: () => {
                if (!onModEnterRef.current) return false
                onModEnterRef.current()
                return true
              },
            },
          ]),
        ),
        basicSetup,
        oneDarkTheme,
        // Ahead of the language so it wins over any highlight style the mode
        // brings along; basicSetup's default style is a fallback below it.
        syntaxHighlighting(atomOneDarkHighlightStyle),
        ...languageExtension(path),
        EditorView.lineWrapping,
        EditorView.updateListener.of((u) => {
          if (u.docChanged) {
            onChangeRef.current(u.state.doc.toString())
          }
        }),
      ],
      parent: ref.current,
    })
    viewRef.current = view
    return () => {
      view.destroy()
      viewRef.current = null
    }
  }, [])
  return <Box ref={ref} height="100%" overflowY="auto" fontSize="sm" />
}

export default CodeEditorPane
