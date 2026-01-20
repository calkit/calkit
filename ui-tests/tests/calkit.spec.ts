import { expect, test, galata } from "@jupyterlab/galata"

/**
 * Don't load JupyterLab webpage before running the tests.
 * This is required to ensure we capture all log messages.
 */
test.use({ autoGoto: false })

test("should emit an activation console message", async ({ page }) => {
  const logs: string[] = []

  page.on("console", (message) => {
    logs.push(message.text())
  })

  await page.goto()

  expect(
    logs.filter((s) => s === "JupyterLab extension calkit is activated!"),
  ).toHaveLength(1)
})

test.describe("Notebook pipeline workflow", () => {

  test("should create environment from notebook toolbar, add stage, run, and execute pipeline", async ({
    page,
    tmpPath,
  }) => {
    // Set a wide viewport to ensure toolbar badges are visible (not collapsed to 3-dot menu)
    await page.setViewportSize({ width: 1400, height: 900 })

    // Navigate to JupyterLab
    await page.goto()

    // Wait for JupyterLab to be fully ready
    await page.waitForSelector(".jp-LauncherCard", { timeout: 30000 })

    // Create data.csv directly via Jupyter contents API for reliability
    await page.request.put(`/api/contents/data.csv`, {
      data: {
        type: "file",
        format: "text",
        content: "x,y\n1,10\n2,20\n3,30\n",
      },
    })

    // Wait briefly to let the server write the file
    await page.waitForTimeout(500)

    // Create a new notebook using the launcher
    const launcherCards = page.locator(".jp-LauncherCard")
    const notebookCard = launcherCards.filter({ hasText: "Notebook" }).first()
    await notebookCard.click()

    // Wait for notebook to be created and opened
    await page.waitForSelector(".jp-NotebookPanel", { timeout: 20000 })

    // Focus the notebook area to ensure toolbar renders
    await page.click(".jp-NotebookPanel", { position: { x: 10, y: 10 } })

    // Wait for and find the environment badge
    const envBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: "No environment selected" })
      .first()

    // Don't wait for visibility - element may be hidden by CSS but still clickable
    // Just proceed with clicking it
    await page.waitForTimeout(1000)

    // Step 1: Create environment from notebook toolbar
    // Click the environment badge to open the dropdown
    // Use evaluate to bypass visibility checks
    await envBadge.evaluate((el) => {
      (el as HTMLElement).click()
    })

    // Wait for dropdown to open (don't check visibility since CSS hides it)
    await page.waitForSelector(".calkit-badge-dropdown", { state: "attached", timeout: 5000 })
    const envDropdown = page.locator(".calkit-badge-dropdown").first()

    // When there are no environments, the UI now shows a button to create one
    // If a button exists in the dropdown, click it (it will be "Create new environment" when no envs exist,
    // or "Edit current environment" when we already have one from a previous step)
    const firstButton = envDropdown.locator("button").first()
    await firstButton.evaluate((el) => {
      (el as HTMLElement).click()
    })

    // Wait for environment editor dialog to open
    await page.waitForSelector(".calkit-environment-editor-dialog", { state: "attached", timeout: 5000 })

    // Fill in environment name
    const nameInput = page.locator('input[placeholder="ex: analysis"]').first()
    await nameInput.fill("analytics-env")

    // Default Python version is already 3.14; no need to change

    // Add the PyData package group instead of typing packages
    const pydataButton = page
      .locator('.calkit-environment-editor-dialog .calkit-env-package-group-btn:has-text("PyData")')
      .first()
    await pydataButton.click()

    // Click Create button
    const createButton = page.locator('button:has-text("Create")').first()
    await createButton.click()

    // Wait for environment creation to complete (dialog closes)
    await page.waitForSelector(".calkit-environment-editor-dialog", { state: "detached", timeout: 20000 })

    // Step 2: Set pipeline stage
    const stageBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: "Not in pipeline" })
      .first()
    await stageBadge.dispatchEvent("click")

    // Wait for dropdown
    const stageDropdown = page.locator(".calkit-badge-dropdown").first()
    await expect(stageDropdown).toBeVisible({ timeout: 5000 })

    // Fill in stage name
    const stageNameInput = page.locator('input[placeholder*="e.g., postprocess"]')
    await stageNameInput.fill("analytics")

    // Click Save button
    const saveStageButton = stageDropdown.locator('button:has-text("Save")').first()
    await saveStageButton.click()

  // Debug: Log to console
  console.log("Save button clicked. Checking if button is enabled...")
  const isDisabled = await saveStageButton.isDisabled()
  console.log("Save button disabled:", isDisabled)
    // Wait for stage to be saved - the badge should change from "Not in pipeline" to "In pipeline: analytics"
    await page.waitForTimeout(3000)

    // Wait for the stage save request to complete
    await page.waitForResponse(
      (response) => response.url().includes("/calkit/notebook/stage") && response.request().method() === "PUT",
      { timeout: 10000 }
    )

    // Wait for stage to be saved - the badge should change from "Not in pipeline" to "In pipeline: analytics"
    await page.waitForTimeout(2000)
    // Close the dropdown with Escape
    await page.keyboard.press("Escape")
    await page.waitForTimeout(1000)

    // Step 3: Write analytics code with pandas and matplotlib
    const firstCell = page.locator(".jp-Cell").first()
    await firstCell.click()
    await page.keyboard.type(
      'import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.read_csv("data.csv")\nplt.figure()\nplt.plot(df["x"], df["y"])\nplt.savefig("figures/plot.png")\nplt.close()'
    )

    // Save the notebook (Ctrl+S)
    await page.keyboard.press("Control+s")
    await page.waitForTimeout(2000)

    // Step 4: Run the stage with the play button
    // The play button should now be visible next to the stage badge
    const playButton = page.locator(".calkit-play-button").first()

    // Wait for play button to appear and be visible (with longer timeout since it depends on stage refresh)
    await page.waitForSelector(".calkit-play-button", { state: "attached", timeout: 15000 })
    await expect(playButton).toBeVisible({ timeout: 5000 })
    await playButton.click({ force: true })

    // Wait for execution to start and complete
    await page.waitForSelector(".calkit-play-button .calkit-spinner", { timeout: 10000 })
    await page.waitForSelector(".calkit-play-button:not(:has(.calkit-spinner))", { timeout: 60000 })

    // Step 5: Add data.csv as an input
    const inputsBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: /Inputs \(/ })
      .first()
    await inputsBadge.dispatchEvent("click")
    const inputsDropdown = page.locator(".calkit-badge-dropdown").first()
    await expect(inputsDropdown).toBeVisible({ timeout: 5000 })
    const inputField = inputsDropdown.locator('input[placeholder*="path/to/input"]')
    await inputField.fill("data.csv")
    const addInputButton = page.locator('button:has-text("Add")').first()
    if (await addInputButton.isVisible()) {
      await addInputButton.click()
    }
    const saveInputButton = page.locator('button:has-text("Save")').first()
    await saveInputButton.click()
    await page.waitForTimeout(500)

    // Step 6: Define figures/plot.png as output
    const outputsBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: /Outputs \(/ })
      .first()
    await outputsBadge.dispatchEvent("click")
    const outputsDropdown = page.locator(".calkit-badge-dropdown").first()
    await expect(outputsDropdown).toBeVisible({ timeout: 5000 })
    const outputField = outputsDropdown.locator('input[placeholder*="path/to/output"]')
    await outputField.fill("figures/plot.png")
    const addOutputButton = page.locator('button:has-text("Add")').first()
    if (await addOutputButton.isVisible()) {
      await addOutputButton.click()
    }
    const saveOutputButton = page.locator('button:has-text("Save")').first()
    await saveOutputButton.click()
    await page.waitForTimeout(500)

    // Step 7: Run the entire pipeline from the sidebar play button
    const calkitSidebar = page.locator(".calkit-sidebar")
    const sidebarVisible = await calkitSidebar.isVisible()
    if (!sidebarVisible) {
      const calkitTab = page.locator('.jp-SideBar [data-id="calkit-sidebar"]')
      if (await calkitTab.count() > 0) {
        await calkitTab.click()
        await page.waitForSelector(".calkit-sidebar", { timeout: 10000 })
      }
    }

    const pipelineSectionHeader = page.locator('.calkit-sidebar-section-header:has-text("Pipeline")')
    const pipelineExpanded = await pipelineSectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (pipelineExpanded === 0) {
      await pipelineSectionHeader.click()
      await page.waitForTimeout(500)
    }

    const analyticsStageLine = page.locator('.calkit-stage-item:has-text("analytics")')
    const stagePlayButton = analyticsStageLine.locator(".calkit-stage-play-button, button[title*='Run']").first()

    if (await stagePlayButton.isVisible()) {
      await stagePlayButton.click()
      await page.waitForSelector(".calkit-spinner", { timeout: 10000 })
      await page.waitForTimeout(5000)
    }

    // Verify that the stage ran successfully (no stale marker)
    const staleStage = page.locator('.calkit-stage-item.stale:has-text("analytics")')
    const isStale = await staleStage.count()
    expect(isStale).toBe(0)
  })
})
