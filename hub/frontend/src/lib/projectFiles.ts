// Fetching project files into memory, for the in-browser runtimes.

import { ProjectsService } from "../client"

// Inputs are what the code reads, so the caps are about what a browser can
// hold, not about tidiness: a profiler's sqlite or a results HDF5 can run
// to hundreds of megabytes and still be exactly what's needed.
export const MAX_INPUT_BYTES = 512 * 1024 * 1024
export const MAX_TOTAL_INPUT_BYTES = 1536 * 1024 * 1024
export const MAX_INPUT_FILES = 5000

export interface FetchBudget {
  bytes: number
  files: number
}

export const newBudget = (): FetchBudget => ({
  bytes: MAX_TOTAL_INPUT_BYTES,
  files: MAX_INPUT_FILES,
})

const bytesOf = async (item: any): Promise<Uint8Array | null> => {
  if (item.content) {
    const binary = atob(item.content)
    const bytes = new Uint8Array(binary.length)
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
    return bytes
  }
  if (item.url) {
    const resp = await fetch(String(item.url))
    return resp.ok ? new Uint8Array(await resp.arrayBuffer()) : null
  }
  return null
}

/**
 * Every file under a repo path, as bytes at their repo paths.
 *
 * A stage input is as often a directory (a stage's output folder, a
 * results tree) as a single file, and code reading from it expects the
 * files inside. Anything that can't be fetched is reported in `problems`
 * rather than dropped: a missing file fails in ways that don't name it
 * (sqlite makes an empty database, pandas finds an empty folder).
 */
export async function fetchTree(
  ownerName: string,
  projectName: string,
  path: string,
  budget: FetchBudget,
  onStatus: (status: string) => void,
  problems: string[],
): Promise<{ path: string; data: Uint8Array }[]> {
  let item: any
  try {
    item = await ProjectsService.getProjectContents({
      owner_name: ownerName,
      project_name: projectName,
      path,
    }).then((response) => response.data as any)
  } catch {
    problems.push(`${path}: not found in the project`)
    return []
  }
  if (!item) return []
  if (item.type === "dir") {
    const out: { path: string; data: Uint8Array }[] = []
    for (const child of (item.dir_items ?? []) as any[]) {
      if (budget.files <= 0 || budget.bytes <= 0) {
        problems.push(`${path}: not fully loaded, the input budget ran out`)
        break
      }
      out.push(
        ...(await fetchTree(
          ownerName,
          projectName,
          String(child.path),
          budget,
          onStatus,
          problems,
        )),
      )
    }
    return out
  }
  if (item.size && item.size > MAX_INPUT_BYTES) {
    problems.push(
      `${path}: ${(item.size / 1e6).toFixed(0)} MB is over the ${
        MAX_INPUT_BYTES / 1024 / 1024
      } MB per-file limit`,
    )
    return []
  }
  if (!item.content && !item.url) {
    problems.push(
      `${path}: this version isn't in the hub's storage; ` +
        "push it with `calkit dvc push` (against this hub) and reopen",
    )
    return []
  }
  onStatus(`Loading ${path}`)
  let data: Uint8Array | null = null
  try {
    data = await bytesOf(item)
  } catch (e) {
    problems.push(`${path}: download failed (${(e as Error).message})`)
    return []
  }
  if (!data) {
    problems.push(`${path}: download failed`)
    return []
  }
  budget.files -= 1
  budget.bytes -= data.length
  return [{ path, data }]
}

/** Bytes as text, for a preview of a text file. */
export const bytesToText = (data: Uint8Array): string =>
  new TextDecoder().decode(data)
