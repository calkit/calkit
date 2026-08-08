/** Pull the ``owner/repo`` out of a GitHub URL, if it names a repository. */
export function getGithubRepo(url: string): string | null {
  const parsed = new URL(url);
  if (parsed.hostname !== "github.com") {
    return null;
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts.length < 2) {
    return null;
  }
  const [owner, repo] = parts;
  // Routes that look like a repo but aren't, e.g. /orgs/calkit/projects
  const reserved = new Set([
    "orgs",
    "settings",
    "notifications",
    "explore",
    "marketplace",
    "sponsors",
    "topics",
    "collections",
    "features",
    "pricing",
    "apps",
    "codespaces",
    "new",
  ]);
  if (reserved.has(owner)) {
    return null;
  }
  return `${owner}/${repo.replace(/\.git$/, "")}`;
}

/** The path being browsed inside a GitHub repo, e.g. from a /blob/ URL. */
export function getGithubPath(url: string): string | null {
  const parsed = new URL(url);
  const parts = parsed.pathname.split("/").filter(Boolean);
  // /owner/repo/(blob|tree)/ref/path...
  if (parts.length < 5 || !["blob", "tree"].includes(parts[2])) {
    return null;
  }
  return parts.slice(4).join("/");
}

/** Pull the project ID out of an Overleaf URL. */
export function getOverleafProjectId(url: string): string | null {
  const parsed = new URL(url);
  if (!/(^|\.)overleaf\.com$/.test(parsed.hostname)) {
    return null;
  }
  const parts = parsed.pathname.split("/").filter(Boolean);
  if (parts[0] !== "project" || !parts[1]) {
    return null;
  }
  return parts[1];
}

export interface DetectedReference {
  doi: string | null;
  arxivId: string | null;
  title: string | null;
  authors: string | null;
  year: string | null;
  journal: string | null;
  url: string;
}

function metaContent(names: string[]): string | null {
  for (const name of names) {
    const selectors = [
      `meta[name="${name}"]`,
      `meta[property="${name}"]`,
      `meta[name="${name}" i]`,
    ];
    for (const selector of selectors) {
      const el = document.querySelector<HTMLMetaElement>(selector);
      if (el?.content?.trim()) {
        return el.content.trim();
      }
    }
  }
  return null;
}

/**
 * Read a repeated meta tag, taking the first scheme that has any values.
 *
 * Publishers commonly emit the same authors under both the Highwire and
 * Dublin Core names, so reading across schemes and concatenating lists
 * every author twice. Case is also inconsistent between publishers, hence
 * matching the tag name case-insensitively rather than listing variants.
 */
function metaContents(names: string[]): string[] {
  for (const name of names) {
    const values: string[] = [];
    const seen = new Set<string>();
    for (const el of document.querySelectorAll<HTMLMetaElement>(
      `meta[name="${name}" i], meta[property="${name}" i]`,
    )) {
      const value = el.content?.trim();
      // One scheme can still repeat a value, e.g. a tag emitted once per
      // affiliation of the same author
      if (value && !seen.has(value.toLowerCase())) {
        seen.add(value.toLowerCase());
        values.push(value);
      }
    }
    if (values.length) {
      return values;
    }
  }
  return [];
}

export function normalizeDoi(value: string | null): string | null {
  if (!value) {
    return null;
  }
  let doi = value.trim().toLowerCase();
  for (const prefix of ["https://doi.org/", "http://doi.org/", "doi:"]) {
    if (doi.startsWith(prefix)) {
      doi = doi.slice(prefix.length);
    }
  }
  doi = doi.replace(/^\/+|[/\s]+$/g, "");
  return /^10\.\d{4,9}\//.test(doi) ? doi : null;
}

export function normalizeArxivId(value: string | null): string | null {
  if (!value) {
    return null;
  }
  let id = value.trim().toLowerCase();
  for (const prefix of [
    "https://arxiv.org/abs/",
    "http://arxiv.org/abs/",
    "arxiv:",
  ]) {
    if (id.startsWith(prefix)) {
      id = id.slice(prefix.length);
    }
  }
  id = id.replace(/^\/+|\/+$/g, "").replace(/v\d+$/, "");
  return /^\d{4}\.\d{4,5}$/.test(id) || /^[a-z-]+(\.[a-z]{2})?\/\d{7}$/.test(id)
    ? id
    : null;
}

/**
 * Read the reference described by the current page.
 *
 * Publishers overwhelmingly publish Highwire Press or Dublin Core citation
 * meta tags, which is what Zotero's own translators lean on, so reading those
 * covers most journals without a per-site scraper.
 */
export function detectReference(
  url: string = window.location.href,
): DetectedReference | null {
  const doi = normalizeDoi(
    metaContent([
      "citation_doi",
      "dc.identifier",
      "DC.identifier",
      "dc.Identifier",
      "prism.doi",
    ]),
  );
  const arxivId =
    normalizeArxivId(metaContent(["citation_arxiv_id"])) ??
    normalizeArxivId(url);
  const title = metaContent([
    "citation_title",
    "dc.title",
    "DC.title",
    "og:title",
  ]);
  if (!doi && !arxivId && !title) {
    return null;
  }
  const authors = metaContents(["citation_author", "dc.creator"]).join(" and ");
  const dateString =
    metaContent([
      "citation_publication_date",
      "citation_date",
      "dc.date",
      "DC.date",
      "prism.publicationDate",
    ]) ?? "";
  const yearMatch = dateString.match(/\d{4}/);
  return {
    doi,
    arxivId,
    title,
    authors: authors || null,
    year: yearMatch ? yearMatch[0] : null,
    journal: metaContent([
      "citation_journal_title",
      "citation_conference_title",
      "prism.publicationName",
    ]),
    url,
  };
}

/**
 * Build a citation key of the form ``lastname2024word``, matching the style
 * Zotero and Better BibTeX produce.
 */
export function suggestCitationKey(reference: DetectedReference): string {
  const firstAuthor = (reference.authors ?? "").split(" and ")[0] ?? "";
  // "Last, First" and "First Last" are both common in citation meta tags
  const lastName = firstAuthor.includes(",")
    ? firstAuthor.split(",")[0]
    : firstAuthor.split(/\s+/).slice(-1)[0];
  const titleWord =
    (reference.title ?? "")
      .split(/\s+/)
      .map((word) => word.replace(/[^A-Za-z0-9]/g, ""))
      .find((word) => word.length > 3) ?? "";
  const key = [
    lastName.replace(/[^A-Za-z0-9]/g, "").toLowerCase(),
    reference.year ?? "",
    titleWord.toLowerCase(),
  ]
    .filter(Boolean)
    .join("");
  return key || "reference";
}

/** The pull request number a GitHub URL names, if it names one. */
export function getGithubPullNumber(url: string): number | null {
  const parts = new URL(url).pathname.split("/").filter(Boolean);
  if (parts.length < 4 || parts[2] !== "pull") {
    return null;
  }
  const number = Number(parts[3]);
  return Number.isInteger(number) && number > 0 ? number : null;
}
