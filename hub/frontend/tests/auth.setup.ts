import { test as setup, expect } from "@playwright/test"
import path from "path"
import { fileURLToPath } from "url"
import dotenv from "dotenv"

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
dotenv.config({ path: path.join(__dirname, "../../.env") })

const authFile = "playwright/.auth/user.json"

setup("authenticate as superuser", async ({ page, request }) => {
  const { FIRST_SUPERUSER, FIRST_SUPERUSER_PASSWORD } = process.env
  if (!FIRST_SUPERUSER || !FIRST_SUPERUSER_PASSWORD) {
    throw new Error("FIRST_SUPERUSER and FIRST_SUPERUSER_PASSWORD must be set")
  }

  // Obtain a JWT from the backend password-login endpoint (superuser only).
  const response = await request.post(
    "http://api.localhost/login/access-token",
    {
      form: {
        username: FIRST_SUPERUSER,
        password: FIRST_SUPERUSER_PASSWORD,
      },
    },
  )
  expect(response.ok()).toBeTruthy()
  const { access_token } = await response.json()

  // Seed the token into the app's localStorage so all subsequent page loads
  // start in an authenticated state. Answering the analytics consent banner
  // keeps it from covering the bottom of every page under test.
  await page.goto("/")
  await page.evaluate((token: string) => {
    localStorage.setItem("access_token", token)
    localStorage.setItem("analytics_consent", "denied")
  }, access_token)

  await page.context().storageState({ path: authFile })
})
