// Sort types/constants for the releases table. Kept out of ReleasesTable.tsx
// so that file only exports a component, which React Fast Refresh requires for
// clean hot-reloading (a non-component value export there invalidates the
// module on every edit).

export type SortKey =
  | "name"
  | "path"
  | "version"
  | "date"
  | "views"
  | "comments"

export type SortDir = "asc" | "desc"

export interface ReleaseSort {
  key: SortKey
  dir: SortDir
}

export const DEFAULT_RELEASE_SORT: ReleaseSort = { key: "date", dir: "desc" }
