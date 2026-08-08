import { beforeEach, describe, expect, test } from "vitest";

import {
  detectReference,
  getGithubPath,
  getGithubRepo,
  getOverleafProjectId,
  normalizeArxivId,
  normalizeDoi,
  suggestCitationKey,
} from "./detect";

describe("getGithubRepo", () => {
  test("reads the repo from repository URLs and ignores everything else", () => {
    expect(getGithubRepo("https://github.com/calkit/calkit")).toBe(
      "calkit/calkit",
    );
    expect(
      getGithubRepo("https://github.com/calkit/calkit/blob/main/README.md"),
    ).toBe("calkit/calkit");
    expect(getGithubRepo("https://github.com/calkit/calkit.git")).toBe(
      "calkit/calkit",
    );
    expect(getGithubRepo("https://github.com/calkit/calkit/pull/1087")).toBe(
      "calkit/calkit",
    );
    // Pages that look like a repo but aren't one
    expect(getGithubRepo("https://github.com/calkit")).toBeNull();
    expect(
      getGithubRepo("https://github.com/orgs/calkit/projects/1"),
    ).toBeNull();
    expect(getGithubRepo("https://github.com/settings/profile")).toBeNull();
    expect(getGithubRepo("https://gitlab.com/calkit/calkit")).toBeNull();
  });
});

describe("getGithubPath", () => {
  test("reads the browsed path out of blob and tree URLs", () => {
    expect(
      getGithubPath("https://github.com/calkit/calkit/blob/main/figures/a.png"),
    ).toBe("figures/a.png");
    expect(
      getGithubPath("https://github.com/calkit/calkit/tree/main/figures"),
    ).toBe("figures");
    expect(getGithubPath("https://github.com/calkit/calkit")).toBeNull();
    expect(
      getGithubPath("https://github.com/calkit/calkit/issues/12"),
    ).toBeNull();
  });
});

describe("getOverleafProjectId", () => {
  test("reads the project ID from Overleaf project URLs", () => {
    expect(
      getOverleafProjectId("https://www.overleaf.com/project/abc123"),
    ).toBe("abc123");
    expect(
      getOverleafProjectId("https://www.overleaf.com/project/abc123/detacher"),
    ).toBe("abc123");
    expect(getOverleafProjectId("https://www.overleaf.com/project")).toBeNull();
    expect(getOverleafProjectId("https://www.overleaf.com/")).toBeNull();
    expect(
      getOverleafProjectId("https://notoverleaf.com/project/abc123"),
    ).toBeNull();
  });
});

describe("normalizeDoi", () => {
  test("strips prefixes and case, and rejects things that aren't DOIs", () => {
    expect(normalizeDoi("10.1234/ABCD")).toBe("10.1234/abcd");
    expect(normalizeDoi("https://doi.org/10.1234/abcd")).toBe("10.1234/abcd");
    expect(normalizeDoi("doi:10.1234/abcd ")).toBe("10.1234/abcd");
    expect(normalizeDoi("not-a-doi")).toBeNull();
    expect(normalizeDoi(null)).toBeNull();
  });
});

describe("normalizeArxivId", () => {
  test("strips prefixes and version suffixes", () => {
    expect(normalizeArxivId("arXiv:2301.01234v2")).toBe("2301.01234");
    expect(normalizeArxivId("https://arxiv.org/abs/2301.01234")).toBe(
      "2301.01234",
    );
    expect(normalizeArxivId("math.GT/0309136")).toBe("math.gt/0309136");
    expect(normalizeArxivId("10.1234/abcd")).toBeNull();
    expect(normalizeArxivId(null)).toBeNull();
  });
});

describe("detectReference", () => {
  beforeEach(() => {
    document.head.replaceChildren();
  });

  const addMeta = (name: string, content: string) => {
    const meta = document.createElement("meta");
    meta.name = name;
    meta.content = content;
    document.head.append(meta);
  };

  test("reads Highwire Press citation tags", () => {
    addMeta("citation_title", "A Study of Things");
    addMeta("citation_author", "Smith, Jane");
    addMeta("citation_author", "Jones, Alex");
    addMeta("citation_doi", "10.1234/ABCD");
    addMeta("citation_publication_date", "2024/03/15");
    addMeta("citation_journal_title", "Journal of Things");
    const reference = detectReference("https://example.org/paper");
    expect(reference).not.toBeNull();
    expect(reference?.title).toBe("A Study of Things");
    expect(reference?.doi).toBe("10.1234/abcd");
    expect(reference?.authors).toBe("Smith, Jane and Jones, Alex");
    expect(reference?.year).toBe("2024");
    expect(reference?.journal).toBe("Journal of Things");
  });

  test("doesn't repeat authors listed under two schemes", () => {
    // Springer and others emit the same people as both citation_author and
    // dc.creator, which used to yield "Thomas, Chris D. and Thomas, Chris D."
    addMeta("citation_title", "A Paper");
    addMeta("citation_author", "Thomas, Chris D.");
    addMeta("dc.creator", "Thomas, Chris D.");
    expect(detectReference("https://example.org/paper")?.authors).toBe(
      "Thomas, Chris D.",
    );
  });

  test("keeps every distinct author within one scheme", () => {
    addMeta("citation_title", "A Paper");
    addMeta("citation_author", "Smith, Jane");
    addMeta("citation_author", "Jones, Alex");
    // Repeated once per affiliation is common and still one author
    addMeta("citation_author", "Smith, Jane");
    expect(detectReference("https://example.org/paper")?.authors).toBe(
      "Smith, Jane and Jones, Alex",
    );
  });

  test("falls back to Dublin Core tags", () => {
    addMeta("dc.title", "Another Paper");
    addMeta("dc.identifier", "10.5555/xyz");
    addMeta("dc.creator", "Doe, John");
    const reference = detectReference("https://example.org/paper");
    expect(reference?.title).toBe("Another Paper");
    expect(reference?.doi).toBe("10.5555/xyz");
  });

  test("reads an arXiv ID from the URL when the page has no DOI", () => {
    addMeta("citation_title", "A Preprint");
    const reference = detectReference("https://arxiv.org/abs/2301.01234v2");
    expect(reference?.arxivId).toBe("2301.01234");
    expect(reference?.doi).toBeNull();
  });

  test("returns nothing on a page that describes no reference", () => {
    expect(detectReference("https://example.org/paper")).toBeNull();
  });
});

describe("suggestCitationKey", () => {
  const base = {
    doi: null,
    arxivId: null,
    title: null,
    authors: null,
    year: null,
    journal: null,
    url: "https://example.org",
  };

  test("builds a lastname-year-word key from what the page provided", () => {
    expect(
      suggestCitationKey({
        ...base,
        authors: "Smith, Jane and Jones, Alex",
        year: "2024",
        title: "A Study of Things",
      }),
    ).toBe("smith2024study");
    // "First Last" ordering is just as common in citation meta tags
    expect(
      suggestCitationKey({
        ...base,
        authors: "Jane Smith",
        year: "2024",
        title: "On the Origin",
      }),
    ).toBe("smith2024origin");
    // Nothing usable still yields a key the user can edit
    expect(suggestCitationKey(base)).toBe("reference");
  });
});
