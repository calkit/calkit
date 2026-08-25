import { describe, expect, it } from "vitest"

import {
  findPublicationCollision,
  isTemplatePublication,
  publicationFolder,
} from "./ImportOverleaf"

describe("publicationFolder", () => {
  it("is the directory of the publication's path", () => {
    expect(publicationFolder("paper/paper.pdf")).toBe("paper")
    expect(publicationFolder("docs/paper/paper.pdf")).toBe("docs/paper")
    expect(publicationFolder("paper.pdf")).toBe("")
  })
})

describe("findPublicationCollision", () => {
  const template = { path: "paper/paper.pdf", title: "The paper" }
  const real = { path: "docs/thesis/thesis.pdf", title: "My thesis" }
  it("spots the template, a real publication, or a bare folder", () => {
    expect(isTemplatePublication(template)).toBe(true)
    expect(isTemplatePublication({ path: "x/x.pdf", title: "The paper" })).toBe(
      true,
    )
    expect(isTemplatePublication(real)).toBe(false)
    // Template in the folder: replaceable, and the publication is named
    expect(findPublicationCollision("paper", [template, real], true)).toEqual({
      folder: "paper",
      publication: template,
      replaceable: true,
    })
    // Sloppy input still matches the folder
    expect(
      findPublicationCollision(" ./paper/ ", [template], false)?.publication,
    ).toBe(template)
    // A real publication is not replaceable by default
    expect(findPublicationCollision("docs/thesis", [real], true)).toEqual({
      folder: "docs/thesis",
      publication: real,
      replaceable: false,
    })
    // A publication nested deeper in the folder still counts
    expect(findPublicationCollision("docs", [real], false)?.publication).toBe(
      real,
    )
    // A folder that exists with no publication declared in it
    expect(findPublicationCollision("figures", [template], true)).toEqual({
      folder: "figures",
      publication: null,
      replaceable: false,
    })
    // Free folder, or nothing typed yet
    expect(
      findPublicationCollision("manuscript", [template, real], false),
    ).toBe(null)
    expect(findPublicationCollision("", [template], true)).toBe(null)
    // A sibling with a shared prefix is not a collision
    expect(findPublicationCollision("pap", [template], false)).toBe(null)
  })
})
