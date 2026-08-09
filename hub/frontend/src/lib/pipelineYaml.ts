import jsYaml from "js-yaml"

// Pure helpers for the pipeline page's linked/highlighted YAML view. Kept
// out of the route module so they can be unit tested without pulling in the
// route's side effects (createFileRoute, syntax-highlighter registration).

/**
 * Heuristic for whether a YAML string token looks like a file path (so it can
 * be linked to the files page). Works for both dvc.yaml and calkit.yaml.
 */
export function looksLikePath(s: string): boolean {
  return (
    s.length > 0 &&
    !s.startsWith("http") &&
    !s.startsWith("git@") &&
    !s.includes(" ") &&
    (s.includes("/") || /\.[a-zA-Z0-9]{1,6}$/.test(s))
  )
}

/** Collect every string in the YAML that looks like a file path. */
export function extractFilePaths(yamlContent: string): Set<string> {
  try {
    const doc = jsYaml.load(yamlContent)
    const paths = new Set<string>()
    function walk(v: unknown) {
      if (typeof v === "string") {
        if (looksLikePath(v)) paths.add(v)
      } else if (Array.isArray(v)) {
        v.forEach(walk)
      } else if (v !== null && typeof v === "object") {
        for (const [k, child] of Object.entries(v as Record<string, unknown>)) {
          if (looksLikePath(k)) paths.add(k)
          walk(child)
        }
      }
    }
    walk(doc)
    return paths
  } catch {
    return new Set()
  }
}

/**
 * Collect the string values of every `environment:` key in the pipeline YAML.
 * These are the tokens we turn into links. A value may be composite
 * ("outer:inner"), which is split and linked per-segment in the renderer.
 */
export function extractEnvRefs(yamlContent: string): Set<string> {
  try {
    const doc = jsYaml.load(yamlContent)
    const refs = new Set<string>()
    function walk(v: unknown) {
      if (Array.isArray(v)) {
        v.forEach(walk)
      } else if (v !== null && typeof v === "object") {
        for (const [k, child] of Object.entries(v as Record<string, unknown>)) {
          if (k === "environment" && typeof child === "string") {
            refs.add(child)
          } else {
            walk(child)
          }
        }
      }
    }
    walk(doc)
    return refs
  } catch {
    return new Set()
  }
}

/**
 * Find the [start, end) line range of a stage's block within the YAML so it
 * can be highlighted. Works for both calkit.yaml (pipeline.stages.<name>) and
 * dvc.yaml (stages.<name>) by matching the stage key at any indent and
 * extending until the next line at the same or lower indentation.
 */
export function findStageLineRange(
  yamlContent: string,
  stage: string,
): [number, number] | null {
  const lines = yamlContent.split("\n")
  const keyRe = new RegExp(
    `^(\\s*)(["']?)${stage.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\2:\\s*(#.*)?$`,
  )
  let start = -1
  let indent = 0
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(keyRe)
    if (m) {
      start = i
      indent = m[1].length
      break
    }
  }
  if (start === -1) return null
  let end = lines.length
  for (let i = start + 1; i < lines.length; i++) {
    const line = lines[i]
    if (line.trim() === "" || line.trim().startsWith("#")) continue
    const curIndent = line.length - line.trimStart().length
    if (curIndent <= indent) {
      end = i
      break
    }
  }
  return [start, end]
}
