import { describe, expect, it } from "vitest"

import { cleanLatex, formatJabrefFile } from "./bibtex"

describe("cleanLatex", () => {
  it("removes protective braces", () => {
    expect(cleanLatex("The {DNS} of {Turbulence}")).toBe(
      "The DNS of Turbulence",
    )
  })

  it("converts accent macros in brace form", () => {
    expect(cleanLatex('Schr{\\"o}dinger')).toBe("Schrödinger")
    expect(cleanLatex("Poincar{\\'e}")).toBe("Poincaré")
  })

  it("converts accent macros in bare form", () => {
    expect(cleanLatex('Schr\\"odinger')).toBe("Schrödinger")
  })

  it("keeps content of formatting wrappers", () => {
    expect(cleanLatex("A \\textbf{bold} idea")).toBe("A bold idea")
    expect(cleanLatex("An \\emph{emphasis}")).toBe("An emphasis")
  })

  it("unescapes punctuation", () => {
    expect(cleanLatex("Cats \\& Dogs")).toBe("Cats & Dogs")
    expect(cleanLatex("50\\% off")).toBe("50% off")
  })

  it("collapses escaped protective braces from a Zotero round-trip", () => {
    expect(cleanLatex("A title for \\{{Cool}\\} \\{{Guy}\\}")).toBe(
      "A title for Cool Guy",
    )
  })

  it("converts dashes", () => {
    expect(cleanLatex("pp. 10--20")).toBe("pp. 10–20")
    expect(cleanLatex("a---b")).toBe("a—b")
  })

  it("collapses whitespace and trims", () => {
    expect(cleanLatex("  too   many   spaces ")).toBe("too many spaces")
  })

  it("leaves plain text untouched", () => {
    expect(cleanLatex("Reynolds number")).toBe("Reynolds number")
  })

  it("expands journal abbreviation macros", () => {
    expect(cleanLatex("\\apjl")).toBe("Astrophysical Journal Letters")
    expect(cleanLatex("\\mnras")).toBe(
      "Monthly Notices of the Royal Astronomical Society",
    )
  })

  it("handles \\url and \\href", () => {
    expect(cleanLatex("\\url{http://dx.doi.org/10.6084/m9.figshare.1}")).toBe(
      "http://dx.doi.org/10.6084/m9.figshare.1",
    )
    expect(cleanLatex("see \\href{http://x.com}{the site}")).toBe(
      "see the site",
    )
  })

  it("drops unknown control words but keeps surrounding text", () => {
    expect(cleanLatex("published in \\somejournal 2013")).toBe(
      "published in 2013",
    )
  })
})

describe("formatJabrefFile", () => {
  it("extracts the file name from JabRef metadata", () => {
    expect(
      formatJabrefFile(
        ":Turbines, Modeling\\\\Neary et al, 2013, USDOE Reference Model" +
          " Turbine Testing, EWTEC.pdf:PDF",
      ),
    ).toBe(
      "Neary et al, 2013, USDOE Reference Model Turbine Testing, EWTEC.pdf",
    )
  })

  it("handles multiple files", () => {
    expect(formatJabrefFile(":a/one.pdf:PDF;:b/two.pdf:PDF")).toBe(
      "one.pdf, two.pdf",
    )
  })
})
