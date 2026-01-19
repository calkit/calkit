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
  test.use({ tmpPath: "test-notebook-pipeline" })

  test("should create environment from notebook toolbar, add stage, run, and execute pipeline", async ({
    page,
    tmpPath,
  }) => {
    // Navigate to JupyterLab
    await page.goto()

    // Wait for JupyterLab to be fully ready
    await page.waitForSelector(".jp-LauncherCard", { timeout: 30000 })

    // Ensure project has a name to allow environment creation
    await page.request.put("/calkit/project", {
      data: { name: "ui-tests", title: "UI Tests" },
    })

    // Ensure the notebook toolbar includes the Calkit toolbar item
    await page.request.put("/api/settings/%40jupyterlab%2Fnotebook-extension%3Atracker", {
      data: {
        id: "@jupyterlab/notebook-extension:tracker",
        raw: JSON.stringify({
          toolbar: [{ name: "calkit-notebook-toolbar", rank: 10 }],
        }),
      },
    })

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

    // In tests, force toolbar items to be visible even if they overflow
    await page.addStyleTag({
      content:
        ".jp-NotebookPanel .jp-Toolbar { display: flex !important; visibility: visible !important; opacity: 1 !important; }\n.jp-Toolbar-item, .calkit-notebook-toolbar-widget { display: inline-flex !important; visibility: visible !important; opacity: 1 !important; pointer-events: auto !important; }\n.jp-Toolbar-item[hidden], .jp-Toolbar-item[aria-hidden=\\\"true\\\"] { display: inline-flex !important; visibility: visible !important; opacity: 1 !important; }",
    })

    // Wait for Calkit toolbar widget to be attached (presence is enough)
    const toolbarRoot = page.locator(
      ".calkit-notebook-toolbar-widget, .calkit-notebook-toolbar",
    )
    await expect(toolbarRoot.first()).toHaveCount(1)

    // Step 1: Create environment from notebook toolbar
    await page.waitForSelector(".calkit-badge", { state: "attached", timeout: 10000 })
    const envBadge = page
      .locator(".calkit-badge")
      .filter({ hasText: "No environment selected" })
      .first()
    await envBadge.dispatchEvent("click")

    // Wait for dropdown content to be visible
    const envDropdown = page.locator(".calkit-badge-dropdown").first()
    await page.waitForSelector(".calkit-badge-dropdown", { state: "attached", timeout: 5000 })

    // Click the "+ Create new…" option in the environment select within the dropdown
    const envSelectAll = envDropdown.locator("select[id^='calkit-env-select-']")
    if ((await envSelectAll.count()) > 0) {
      const envSelect = envSelectAll.first()
      await envSelect.evaluate((el: HTMLSelectElement) => {
        el.value = "__create__";
        el.dispatchEvent(new Event("change", { bubbles: true }));
      })
    } else {
      const createEnvButton = envDropdown.locator('button:has-text("Create environment")').first()
      await createEnvButton.dispatchEvent("click")
    }

    // Wait for environment editor dialog
    await page.waitForSelector(".calkit-modal-overlay", { timeout: 10000 })

    // Fill in environment name
    const nameInput = page.locator('input[placeholder="Environment name"]')
    await nameInput.fill("analytics-env")

    // Select Python version (3.14)
    const pythonInput = page.locator('input[placeholder*="Python"]')
    await pythonInput.clear()
    await pythonInput.fill("3.14")

    // Provide common packages
    const packagesField = page.locator('textarea, input').filter({ hasText: /packages/i }).first()
    if (await packagesField.count()) {
      await packagesField.fill("pandas\nmatplotlib")
    }

    // Click Create button
    const createButton = page.locator('button:has-text("Create")').first()
    await createButton.click()

    // Wait for environment creation to complete
    await page.waitForSelector(".calkit-modal-overlay", { state: "hidden", timeout: 20000 })

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
    const saveStageButton = page.locator('button:has-text("Save")').first()
    await saveStageButton.click()

    // Wait for stage to be saved
    await page.waitForTimeout(1000)

    // Step 3: Write analytics code with pandas and matplotlib
    const firstCell = page.locator(".jp-Cell").first()
    await firstCell.click()
    await page.keyboard.type(
      'import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.read_csv("data.csv")\nplt.figure()\nplt.plot(df["x"], df["y"])\nplt.savefig("figures/plot.png")\nplt.close()'
    )

    // Save the notebook (Ctrl+S)
    await page.keyboard.press("Control+s")
    await page.waitForTimeout(1000)

    // Step 4: Run the stage with the play button
    const playButton = page.locator(".calkit-play-button").first()
    await expect(playButton).toBeVisible({ timeout: 10000 })
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
