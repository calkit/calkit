import { expect, test } from "@playwright/test"
import { firstSuperuser, firstSuperuserPassword } from "./config"

test.describe("Unauthenticated", () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test("Shows GitHub sign-in button", async ({ page }) => {
    await page.goto("/login")
    await expect(
      page.getByRole("button", { name: "Sign in with GitHub" }),
    ).toBeVisible()
  })

  test("Clicking sign-in navigates to GitHub OAuth", async ({ page }) => {
    await page.goto("/login")

    const [nav] = await Promise.all([
      page.waitForNavigation(),
      page.getByRole("button", { name: "Sign in with GitHub" }).click(),
    ])

    // GitHub may redirect to /login before /login/oauth/authorize if the browser
    // isn't already signed into GitHub; just verify we landed on github.com with
    // the OAuth path somewhere in the URL (possibly URL-encoded in return_to).
    const url = decodeURIComponent(nav?.url() || page.url())
    expect(url).toContain("github.com")
    expect(url).toMatch(/login\/oauth\/authorize|oauth\/authorize/)
  })

  test("Device approval asks for login then returns to approval page", async ({
    page,
    request,
  }) => {
    const deviceCode = "test-device-code"

    await page.goto(`/login/device?device_code=${deviceCode}`)
    await expect(page.getByText("Authorize CLI Access")).toBeVisible()
    await expect(
      page.getByText("You need to sign in before authorizing this CLI request."),
    ).toBeVisible()

    await page.getByRole("button", { name: "Log in to authorize" }).click()
    await page.waitForURL((url) => url.pathname === "/login")

    const postLoginRedirect = await page.evaluate(() =>
      localStorage.getItem("post_login_redirect"),
    )
    expect(postLoginRedirect).toBe(`/login/device?device_code=${deviceCode}`)

    const response = await request.post("http://api.localhost/login/access-token", {
      form: {
        username: firstSuperuser,
        password: firstSuperuserPassword,
      },
    })
    expect(response.ok()).toBeTruthy()
    const { access_token } = await response.json()

    await page.evaluate((token: string) => {
      localStorage.setItem("access_token", token)
    }, access_token)

    await page.goto("/login")
    await page.waitForURL(
      (url) =>
        url.pathname === "/login/device" &&
        url.searchParams.get("device_code") === deviceCode,
    )

    await expect(page.getByRole("button", { name: "Authorize CLI" })).toBeVisible()
  })
})

// Uses the real auth storage state from auth.setup.ts (project default).
test("Already authenticated users are redirected off /login", async ({ page }) => {
  await page.goto("/login")
  await page.waitForURL((url) => url.pathname === "/")
})
