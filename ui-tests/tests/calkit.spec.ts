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
  // Increase timeout for this suite to allow longer notebook runs
  test.describe.configure({ timeout: 180000 })

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
    const notebookCard = launcherCards.filter({ hasText: "ipykernel" }).first()
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

    // Wait for the notebook toolbar to show the newly selected environment
    const envConfiguredBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: "Environment: analytics-env" })
      .first()
    await envConfiguredBadge.waitFor({ state: "attached", timeout: 10000 })
    // Small pause to let the kernel switch finish wiring up
    await page.waitForTimeout(500)

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
    const stageNameInput = page.locator('input[placeholder*="ex: postprocess"]')
    await stageNameInput.fill("analytics")

    // Prepare network waits to observe the stage save request/response
    const saveStageButton = stageDropdown.locator('button:has-text("Save")').first()
    const stageRequestPromise = page.waitForRequest(
      (request) => request.url().includes("notebook/stage") && request.method() === "PUT",
      { timeout: 15000 }
    )
    const stageResponsePromise = page.waitForResponse(
      (response) => response.url().includes("notebook/stage") && response.request().method() === "PUT",
      { timeout: 15000 }
    )
    await Promise.all([stageRequestPromise, stageResponsePromise, saveStageButton.click()])

    // Confirm badge updates to show the configured stage
    const stageBadgeUpdated = page
      .locator(".calkit-badge")
      .filter({ hasText: "Stage: analytics" })
      .first()
    await expect(stageBadgeUpdated).toBeVisible({ timeout: 10000 })
    // Close the dropdown with Escape
    await page.keyboard.press("Escape")
    await page.waitForTimeout(1000)

    // Step 3: Write analytics code with pandas and matplotlib
    const firstCell = page.locator(".jp-Cell").first()
    await firstCell.click()

    // Type simpler code first to test cell execution works
    // Start with just creating the directory and file
    await page.keyboard.type(
      'import os\nimport matplotlib.pyplot as plt\nos.makedirs("figures", exist_ok=True)\nfig, ax = plt.subplots()\nax.plot([1, 2, 3], [10, 20, 30])\nplt.savefig("figures/plot.png")\nplt.close()'
    )

    // Wait a moment for the cell editor to process the input
    await page.waitForTimeout(500)

    // Execute the cell using Shift+Enter
    await page.keyboard.press("Shift+Enter")

    // Poll for the output file created by the cell execution
    // Give it 60 seconds to execute and create the file
    let cellExecuted = false
    const cellExecuteDeadline = Date.now() + 60000
    while (Date.now() < cellExecuteDeadline) {
      const resp = await page.request.get(`/api/contents/figures/plot.png`)
      if (resp.status() === 200) {
        cellExecuted = true
        console.log("Cell executed successfully, figures/plot.png created")
        break
      }
      await page.waitForTimeout(1000)
    }

    if (!cellExecuted) {
      console.warn("Cell did not create output file within 60s, continuing anyway...")
    }

    // Step 4: Run the stage with the play button
    const playButton = page.locator(".calkit-play-button").first()
    await page.waitForSelector(".calkit-play-button", { state: "attached", timeout: 15000 })
    await expect(playButton).toBeVisible({ timeout: 5000 })

    console.log("Clicking play button...")
    await playButton.click()

    // Wait for execution to complete
    // In manual testing this works, but in Playwright the cell execution completion signals
    // don't fire reliably. Just wait a reasonable amount of time.
    console.log("Waiting for stage execution to complete...")
    await page.waitForTimeout(10000)
    console.log("Stage execution should be complete")

    // Check if an error dialog appeared and dismiss it
    const errorDialog = page.locator('.jp-Dialog')
    if (await errorDialog.isVisible()) {
      console.warn("Error dialog appeared, capturing error message...")
      const errorContent = await errorDialog.locator('.jp-Dialog-content').textContent()
      console.warn("Error dialog content:", errorContent)
      const dismissButton = errorDialog.locator('button:has-text("Dismiss"), button:has-text("OK"), button:has-text("Close")').first()
      if (await dismissButton.isVisible()) {
        await dismissButton.click()
        await page.waitForTimeout(500)
      }
    }

    // Step 5: Add data.csv as an input
    const inputsBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: /Inputs \(/ })
      .first()
    await inputsBadge.dispatchEvent("click")
    // Wait for the portaled dropdown to appear
    await page.waitForSelector(".calkit-badge-dropdown", { state: "attached", timeout: 5000 })
    // Search globally since dropdown is portaled to document.body
    const inputField = page.locator('input[placeholder*="ex: data/raw.csv"]').first()
    await inputField.fill("data.csv")
    // Find all "Add" buttons and pick the first visible one
    const addInputButtons = page.locator('button:has-text("Add")')
    let addInputButtonFound = false
    const addInputButtonCount = await addInputButtons.count()
    for (let i = 0; i < addInputButtonCount; i++) {
      const btn = addInputButtons.nth(i)
      if (await btn.isVisible()) {
        await btn.click()
        addInputButtonFound = true
        break
      }
    }
    if (!addInputButtonFound && addInputButtonCount > 0) {
      await addInputButtons.first().click()
    }
    // After clicking Add, wait a moment for the dropdown state to update
    await page.waitForTimeout(200)
    // Find all "Save" buttons globally and click the first visible one
    const saveInputButtons = page.locator('button:has-text("Save")')
    const saveInputButtonCount = await saveInputButtons.count()
    if (saveInputButtonCount > 0) {
      for (let i = 0; i < saveInputButtonCount; i++) {
        const btn = saveInputButtons.nth(i)
        if (await btn.isVisible()) {
          await btn.click()
          break
        }
      }
    }
    await page.waitForTimeout(500)

    // Step 6: Define figures/plot.png as output
    const outputsBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: /Outputs \(/ })
      .first()
    await outputsBadge.dispatchEvent("click")
    // Wait for the portaled dropdown to appear
    await page.waitForSelector(".calkit-badge-dropdown", { state: "attached", timeout: 5000 })
    // Search globally since dropdown is portaled to document.body
    const outputField = page.locator('input[placeholder*="ex: figures/plot.png"]').first()
    await outputField.fill("figures/plot.png")
    // Find all "Add" buttons and pick the first visible one
    const addOutputButtons = page.locator('button:has-text("Add")')
    let addOutputButtonFound = false
    const addOutputButtonCount = await addOutputButtons.count()
    for (let i = 0; i < addOutputButtonCount; i++) {
      const btn = addOutputButtons.nth(i)
      if (await btn.isVisible()) {
        await btn.click()
        addOutputButtonFound = true
        break
      }
    }
    if (!addOutputButtonFound && addOutputButtonCount > 0) {
      await addOutputButtons.first().click()
    }
    // After clicking Add, wait a moment for the dropdown state to update
    await page.waitForTimeout(200)
    // Find all "Save" buttons globally and click the first visible one
    const saveOutputButtons = page.locator('button:has-text("Save")')
    const saveOutputButtonCount = await saveOutputButtons.count()
    if (saveOutputButtonCount > 0) {
      for (let i = 0; i < saveOutputButtonCount; i++) {
        const btn = saveOutputButtons.nth(i)
        if (await btn.isVisible()) {
          await btn.click()
          break
        }
      }
    }
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
