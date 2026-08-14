import { type Page, type Route, expect, test } from "@playwright/test"

// The figures listing is paginated server-side, so these drive the page
// against a stubbed listing: the point is the paging/keyboard/loading
// behaviour, not the backend, and pointing at a real project's figures would
// make the assertions depend on whatever happens to be committed to it.
//
// Only the figures endpoints are stubbed, so the surrounding project page
// still has to render for real. That needs a project the logged-in user can
// read, which there's no fixture for yet -- so these are opt-in:
//
//   E2E_OWNER=<owner> E2E_PROJECT=<project> npx playwright test figures
//
// Skipped otherwise rather than failing, so CI stays green until a seeded
// project exists to point them at.

const OWNER = process.env.E2E_OWNER
const PROJECT = process.env.E2E_PROJECT

test.skip(
  !OWNER || !PROJECT,
  "Set E2E_OWNER and E2E_PROJECT to a readable project to run these",
)
const TOTAL = 45
const PER_PAGE = 20
const FIGURES_URL = `/${OWNER}/${PROJECT}/figures`

const allPaths = Array.from(
  { length: TOTAL },
  (_, i) => `figures/fig${String(i).padStart(3, "0")}.png`,
)

// 1x1 transparent PNG, so thumbnails render as real images.
const PIXEL =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

const LISTING_PATH = `/projects/${OWNER}/${PROJECT}/figures`

// Predicates rather than globs: the listing and the single-figure route share
// a prefix and differ only by a trailing segment, which glob wildcards blur.
async function stubApi(page: Page, opts: { pageDelayMs?: number } = {}) {
  await page.route(
    (url) => url.pathname.startsWith(`${LISTING_PATH}/`),
    async (route: Route) => {
      // Single figure, used by the compare modal for a figure that isn't on
      // the loaded page.
      const path = decodeURIComponent(
        new URL(route.request().url()).pathname.slice(
          `${LISTING_PATH}/`.length,
        ),
      )
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          path,
          title: path,
          content: PIXEL,
          comment_count: 0,
          storage: "git",
        }),
      })
    },
  )
  // Only the figures endpoints are stubbed; everything else (auth, project
  // metadata, layout) goes to the real backend so the page renders normally.
  await page.route(
    (url) => url.pathname === LISTING_PATH,
    async (route: Route) => {
      const url = new URL(route.request().url())
      const limit = Number(url.searchParams.get("limit") ?? PER_PAGE)
      const offset = Number(url.searchParams.get("offset") ?? 0)
      const q = (url.searchParams.get("q") ?? "").toLowerCase()
      const matched = q ? allPaths.filter((p) => p.includes(q)) : allPaths
      // Delay everything but the very first page so the loading state is
      // observable rather than a race.
      if (opts.pageDelayMs && (offset > 0 || q)) {
        await new Promise((r) => setTimeout(r, opts.pageDelayMs))
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: matched.slice(offset, offset + limit).map((p) => ({
            path: p,
            title: p,
            content: PIXEL,
            comment_count: 0,
            storage: "git",
          })),
          total: matched.length,
          limit,
          offset,
        }),
      })
    },
  )
}

const range = (page: Page) => page.getByText(/\d+–\d+ of \d+/)

test("pages with arrow keys, first/last buttons, and shows loading state", async ({
  page,
}) => {
  await stubApi(page, { pageDelayMs: 700 })
  await page.goto(FIGURES_URL)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)

  // Right arrow advances a page, left arrow goes back.
  await page.keyboard.press("ArrowRight")
  await expect(range(page)).toHaveText(`21–40 of ${TOTAL}`)
  await expect(page).toHaveURL(/page=2/)
  await page.keyboard.press("ArrowLeft")
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
  await expect(page).not.toHaveURL(/page=/)

  // Last/first page jump straight to the ends.
  await page.getByRole("button", { name: "Last page" }).click()
  await expect(range(page)).toHaveText(`41–45 of ${TOTAL}`)
  await page.getByRole("button", { name: "First page" }).click()
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)

  // Left at the first page and right at the last are no-ops, not wraps.
  await page.keyboard.press("ArrowLeft")
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
})

test("dims the stale grid behind a spinner while the next page loads", async ({
  page,
}) => {
  await stubApi(page, { pageDelayMs: 1500 })
  await page.goto(FIGURES_URL)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
  const grid = page.locator('[aria-busy]')
  await expect(grid).toHaveAttribute("aria-busy", "false")

  await page.keyboard.press("ArrowRight")
  // Old thumbnails stay put, but marked busy and covered by a spinner.
  await expect(grid).toHaveAttribute("aria-busy", "true")
  await expect(page.locator(".chakra-spinner").first()).toBeVisible()
  await expect(range(page)).toHaveText(`21–40 of ${TOTAL}`)
  await expect(grid).toHaveAttribute("aria-busy", "false")
})

test("carousel arrows roll over onto the neighbouring page", async ({
  page,
}) => {
  await stubApi(page)
  // Open the last figure of page 1. Rollover is driven off the loaded page's
  // contents, so wait for the grid and the modal before touching the keys.
  await page.goto(`${FIGURES_URL}?path=figures%2Ffig019.png`)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
  await expect(page.getByRole("dialog")).toBeVisible()

  // Right from the end of a page pulls in the next page and opens its first.
  await page.keyboard.press("ArrowRight")
  await expect(page).toHaveURL(/page=2/)
  await expect(page).toHaveURL(/path=figures%2Ffig020\.png/)
  // The grid behind the modal is the signal that the new page has actually
  // rendered. A rollover in flight deliberately ignores further presses, and
  // the URL updates a render before that state clears, so asserting on the
  // URL alone would fire the next key into the gap.
  await expect(range(page)).toHaveText(`21–40 of ${TOTAL}`)

  // Left from the start of a page goes back and opens the previous last.
  await page.keyboard.press("ArrowLeft")
  await expect(page).toHaveURL(/path=figures%2Ffig019\.png/)
  await expect(page).not.toHaveURL(/page=2/)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
})

test("holds off comment/history fetches while flipping the carousel", async ({
  page,
}) => {
  await stubApi(page)
  const commentsPath = `/projects/${OWNER}/${PROJECT}/comments`
  const historyPath = `/projects/${OWNER}/${PROJECT}/git/file-history`
  const hits = { comments: 0, history: 0 }
  await page.route(
    (url) => url.pathname === commentsPath || url.pathname === historyPath,
    async (route: Route) => {
      const p = new URL(route.request().url()).pathname
      if (route.request().method() === "GET") {
        if (p === commentsPath) hits.comments += 1
        else hits.history += 1
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: "[]",
      })
    },
  )

  await page.goto(`${FIGURES_URL}?path=figures%2Ffig000.png`)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)
  await expect(page.getByRole("dialog")).toBeVisible()
  // Let the first figure's panels settle, then measure only what flipping adds.
  await expect.poll(() => hits.history).toBeGreaterThan(0)
  await page.waitForTimeout(600)
  const before = { ...hits }

  // Flip through six figures faster than the settle delay.
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press("ArrowRight")
  }
  await expect(page).toHaveURL(/path=figures%2Ffig006\.png/)

  // Only the figure actually landed on fetches, not every one passed through.
  await expect
    .poll(() => hits.history - before.history, { timeout: 5000 })
    .toBeGreaterThan(0)
  await page.waitForTimeout(600)
  expect(hits.history - before.history).toBeLessThanOrEqual(2)
  expect(hits.comments - before.comments).toBeLessThanOrEqual(2)
})

test("search filters across all pages and keeps arrows in the box", async ({
  page,
}) => {
  await stubApi(page, { pageDelayMs: 900 })
  await page.goto(FIGURES_URL)
  await expect(range(page)).toHaveText(`1–20 of ${TOTAL}`)

  const box = page.getByPlaceholder("Search figures…")
  await box.fill("fig04")
  // The gallery spinner covers the search wait too, so there's no second one.
  await expect(page.locator(".chakra-spinner").first()).toBeVisible()
  // fig040-fig044 match, so search reached beyond the first page of 20.
  await expect(range(page)).toHaveText("1–5 of 5")

  // Arrow keys inside the search box must edit text, not page the grid.
  await box.focus()
  await page.keyboard.press("ArrowLeft")
  await page.keyboard.press("ArrowRight")
  await expect(page).not.toHaveURL(/page=/)
})
