// Subsets of the hub's API schema, covering only the fields this extension
// reads. The hub's OpenAPI client is the full definition; duplicating a
// little here keeps the extension free of a build-time dependency on it.

export interface UserPublic {
  id: string;
  email: string;
  full_name?: string | null;
  account_name?: string | null;
  github_username?: string | null;
}

export interface ProjectPublic {
  id: string;
  name: string;
  title: string;
  description?: string | null;
  git_repo_url: string;
  is_public: boolean;
  owner_account_name: string;
  current_user_access?: "read" | "write" | "admin" | "owner" | null;
}

export interface ProjectsPublic {
  data: ProjectPublic[];
  count: number;
}

export interface StageStatus {
  status:
    | "up-to-date"
    | "stale"
    | "not-run"
    | "unknown"
    | "always-run"
    | "frozen";
  modified_command: boolean;
  modified_inputs: string[];
  modified_outputs: string[];
  missing_outputs: string[];
}

export interface OverleafSyncStatusFile {
  path: string;
  project_path: string;
  state: "new" | "modified" | "deleted";
  figure: boolean;
  stage?: string | null;
  stage_status?: StageStatus | null;
}

export interface OverleafSyncStatus {
  path: string;
  overleaf_project_id?: string | null;
  overleaf_url?: string | null;
  last_sync_commit?: string | null;
  project_commit: string;
  overleaf_commit: string;
  commits_from_overleaf: number;
  files_to_push: OverleafSyncStatusFile[];
  files_to_delete: OverleafSyncStatusFile[];
  in_sync: boolean;
}

export interface OverleafLinkPublic {
  overleaf_project_id: string;
  path: string;
  project_owner_name: string;
  project_name: string;
  project_title: string;
  current_user_access?: "read" | "write" | "admin" | "owner" | null;
}

export interface OverleafLookup {
  links: OverleafLinkPublic[];
  /** Projects read during this lookup, and how many were left. */
  projects_scanned: number;
  projects_remaining: number;
}

export interface OverleafSyncResponse {
  commits_from_overleaf: number;
  overleaf_commit: string;
  project_commit: string;
  committed_overleaf: boolean;
  committed_project: boolean;
}

export interface ContentsItemBase {
  name: string;
  path: string;
  type?: string | null;
  size?: number | null;
  in_repo: boolean;
  content?: string | null;
  url?: string | null;
  calkit_object?: Record<string, unknown> | null;
  storage?: "git" | "dvc" | "dvc-zip" | null;
  /** Content hash of a DVC output; equal hashes mean the same file. */
  md5?: string | null;
  stage?: string | null;
}

/** A DVC-tracked output as it stands at one Git ref. */
export interface DvcOutput {
  path: string;
  name: string;
  type?: string | null;
  size?: number | null;
  md5?: string | null;
  storage?: "dvc" | "dvc-zip" | null;
  /** Presigned, and specific to this ref's version of the artifact. */
  url?: string | null;
}

export interface ContentsItem extends ContentsItemBase {
  dir_items?: ContentsItemBase[] | null;
}

export interface Figure {
  path: string;
  title: string;
  description?: string | null;
  stage?: string | null;
  stage_status?: StageStatus | null;
  url?: string | null;
  content?: string | null;
  storage?: "git" | "dvc" | "dvc-zip" | null;
}

export interface ReferenceEntry {
  type: string;
  key: string;
  file_path?: string | null;
  url?: string | null;
  attrs: Record<string, string>;
  zotero_item_key?: string | null;
  has_pdf: boolean;
  note_count: number;
}

export interface ReferenceZoteroLink {
  library_type: "user" | "group";
  library_id: string;
  collection_key: string;
  collection_name?: string | null;
  last_synced?: string | null;
}

export interface References {
  path: string;
  entries?: ReferenceEntry[] | null;
  zotero?: ReferenceZoteroLink | null;
  stages?: string[] | null;
}

export interface ReferenceSearchMatch {
  project_owner_name: string;
  project_name: string;
  project_title: string;
  path: string;
  key: string;
  type: string;
  title?: string | null;
  doi?: string | null;
  note_count: number;
  matched_on: "doi" | "arxiv_id" | "title";
}

export interface ReferenceNote {
  text: string;
  highlight?: { position: Record<string, unknown>; quote: string } | null;
}

/**
 * What a repo's calkit.yaml says about itself, read straight from GitHub.
 *
 * A project declares the hub it belongs to, so the file is a more direct
 * answer than asking one hub whether it knows the repo. An absent `hub`
 * key means calkit.io, matching the Python package.
 */
export interface CalkitYamlInfo {
  present: boolean;
  /**
   * Hub the project belongs to, already resolved: a declared hub, or
   * calkit.io when the file names none. Null only when there's no
   * calkit.yaml to read, where the repo isn't a Calkit project at all.
   */
  hubUrl: string | null;
}

/** The fields of a GitHub repo the extension uses, from GET /user/github/repos. */
export interface GithubRepo {
  full_name: string;
  name: string;
  description?: string | null;
  private: boolean;
}

/** The refs a pull request compares, from the GitHub API. */
export interface PullRequestRefs {
  number: number;
  title: string;
  head_ref: string;
  base_ref: string;
  head_sha: string;
  base_sha: string;
}
