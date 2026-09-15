import { ChakraProvider } from "@chakra-ui/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"

import type { Table } from "../../client"
import TableView from "./TableView"

const CSV = ["name,value,note", "a,3,x", "b,1,y", "c,2,z"].join("\n")

const table: Table = {
  path: "results/table.csv",
  title: "Table",
  content: btoa(CSV),
}

/** Render the way the tables page does: every piece of state driven by props.
 *
 * The callbacks are what put TableView in controlled mode for each piece of
 * state, so they're supplied here even though nothing asserts on them.
 */
function render(props: Partial<React.ComponentProps<typeof TableView>>) {
  const noop = () => {}
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <ChakraProvider>
        <TableView
          table={table}
          onSearchChange={noop}
          onSortChange={noop}
          onHiddenColumnsChange={noop}
          {...props}
        />
      </ChakraProvider>
    </QueryClientProvider>,
  )
}

/** The rendered rows, as the cell text of each, in the order they appear.
 *
 * Scoped to the table body because the rest of the markup names every column
 * regardless of what's shown: the column menu lists the hidden ones so they
 * can be brought back, and Chakra's emitted CSS mentions plenty besides.
 */
function renderedRows(html: string): string[][] {
  const body = html.slice(html.indexOf("<tbody"), html.indexOf("</tbody>"))
  return body
    .split("<tr")
    .slice(1)
    .map((row) =>
      [...row.matchAll(/>([^<>]*)<\/td>/g)]
        .map((m) => m[1])
        // The first cell of every row is its file line number, not data.
        .slice(1),
    )
}

describe("TableView", () => {
  it("renders every column in file order by default", () => {
    expect(renderedRows(render({}))).toEqual([
      ["a", "3", "x"],
      ["b", "1", "y"],
      ["c", "2", "z"],
    ])
  })

  it("sorts by the column named in the sort spec", () => {
    expect(renderedRows(render({ sort: "2:desc" })).map((r) => r[0])).toEqual([
      "a",
      "c",
      "b",
    ])
    expect(renderedRows(render({ sort: "2:asc" })).map((r) => r[0])).toEqual([
      "b",
      "c",
      "a",
    ])
  })

  it("suspends a sort by a hidden column", () => {
    // A link can carry both, and ordering rows by a column nobody can see
    // reads as the table being scrambled.
    expect(
      renderedRows(render({ sort: "2:desc", hiddenColumns: "2" })),
    ).toEqual([
      ["a", "x"],
      ["b", "y"],
      ["c", "z"],
    ])
    // Showing the column again brings its order back, so hiding is undoable.
    expect(renderedRows(render({ sort: "2:desc" })).map((r) => r[0])).toEqual([
      "a",
      "c",
      "b",
    ])
  })

  it("hides the columns named in the hide spec", () => {
    expect(renderedRows(render({ hiddenColumns: "2-3" }))).toEqual([
      ["a"],
      ["b"],
      ["c"],
    ])
  })

  it("searches only the columns still on screen", () => {
    // "x" lives in the hidden note column, so nothing matches it.
    expect(renderedRows(render({ search: "x" }))).toEqual([["a", "3", "x"]])
    expect(renderedRows(render({ search: "x", hiddenColumns: "3" }))).toEqual(
      [],
    )
  })

  it("seeds the search box from the search prop", () => {
    expect(render({ search: "b" })).toContain('value="b"')
  })
})
