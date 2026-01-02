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

  test("should create notebook, set environment, add to pipeline, and run", async ({
    page,
    tmpPath,
  }) => {
    // Initialize git repository in the test directory
    // This is needed for Calkit to work properly
    await page.evaluate(async (path) => {
      const response = await fetch("/calkit/git/init", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      })
      return response.ok
    }, tmpPath)

    // Navigate to JupyterLab
    await page.goto()

    // Wait for JupyterLab to be ready
    await page.waitForSelector(".jp-LauncherCard", { timeout: 30000 })

    // Open Calkit sidebar if not already open
    const calkitSidebar = page.locator(".calkit-sidebar")
    const sidebarVisible = await calkitSidebar.isVisible()

    if (!sidebarVisible) {
      // Click the Calkit tab in the left sidebar
      const calkitTab = page.locator('.jp-SideBar [data-id="calkit-sidebar"]')
      if (await calkitTab.count() > 0) {
        await calkitTab.click()
        await page.waitForSelector(".calkit-sidebar", { timeout: 10000 })
      }
    }

    // Step 1: Create a new environment
    // Find and expand environments section
    const envSectionHeader = page.locator(
      '.calkit-sidebar-section-header:has-text("Environments")',
    )

    // Check if section is collapsed, if so expand it
    const isExpanded = await envSectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (isExpanded === 0) {
      await envSectionHeader.click()
    }

    // Click create environment button (+)
    const createEnvButton = envSectionHeader.locator(
      ".calkit-sidebar-section-create",
    )
    await createEnvButton.click()

    // Fill in environment dialog
    await page.waitForSelector(".calkit-modal-overlay", { timeout: 5000 })

    const nameInput = page.locator('input[placeholder="Environment name"]')
    await nameInput.fill("test-env")

    // Select venv as the kind
    const kindSelect = page.locator("select").first()
    await kindSelect.selectOption({ label: "venv" })

    // Click Create button
    const createButton = page.locator('.calkit-modal-content button:has-text("Create")')
    await createButton.click()

    // Wait for modal to close and environment to be created
    await page.waitForSelector(".calkit-modal-overlay", {
      state: "hidden",
      timeout: 10000,
    })

    // Step 2: Create a new notebook
    const notebooksSectionHeader = page.locator(
      '.calkit-sidebar-section-header:has-text("Notebooks")',
    )

    // Expand notebooks section if needed
    const notebooksExpanded = await notebooksSectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (notebooksExpanded === 0) {
      await notebooksSectionHeader.click()
    }

    // Click create notebook button
    const createNotebookButton = notebooksSectionHeader.locator(
      ".calkit-sidebar-section-create",
    )
    await createNotebookButton.click()

    // Fill in notebook creation dialog
    await page.waitForSelector(".calkit-modal-overlay", { timeout: 5000 })

    const notebookPathInput = page.locator('input[placeholder*="path"]').first()
    await notebookPathInput.fill("test_notebook.ipynb")

    // Select the environment
    const envSelect = page.locator("select").first()
    await envSelect.selectOption({ label: "test-env" })

    // Click Create
    const createNbButton = page.locator('.calkit-modal-content button:has-text("Create")')
    await createNbButton.click()

    // Wait for notebook to be created and opened
    await page.waitForTimeout(3000)
    await page.waitForSelector(".jp-NotebookPanel", { timeout: 10000 })

    // Step 3: Add content to the notebook
    // Wait for the notebook to be fully loaded
    await page.waitForSelector(".jp-Cell", { timeout: 5000 })

    // Click on the first cell to make it active
    const firstCell = page.locator(".jp-Cell").first()
    await firstCell.click()

    // Enter code into the cell
    await page.keyboard.type(
      'with open("output.txt", "w") as f:\n    f.write("Hello from test!")',
    )

    // Save the notebook (Ctrl+S)
    await page.keyboard.press("Control+s")
    await page.waitForTimeout(1000)

    // Step 4: Set up the pipeline stage
    // Look for the notebook toolbar (stage badge)
    const stageBadge = page.locator(
      '.calkit-badge-with-action:has-text("Not in pipeline")',
    ).first()
    await stageBadge.click()

    // Wait for dropdown to appear
    await page.waitForTimeout(500)

    // Fill in stage name
    const stageNameInput = page.locator('input[placeholder*="stage"]').first()
    await stageNameInput.fill("test-stage")

    // Fill in outputs
    const outputsTextarea = page.locator("textarea").filter({ hasText: /outputs/i }).first()
    if (await outputsTextarea.count() === 0) {
      // Try alternative selector
      const outputFields = page.locator('textarea, input[type="text"]').filter({ has: page.locator('label:has-text("Output")') })
      if (await outputFields.count() > 0) {
        await outputFields.first().fill("output.txt")
      }
    } else {
      await outputsTextarea.fill("output.txt")
    }

    // Save the stage
    const saveButton = page.locator('button:has-text("Save")').first()
    await saveButton.click()

    // Wait for stage to be saved
    await page.waitForTimeout(1000)

    // Step 5: Run the stage
    // Look for the play button in the notebook toolbar
    const playButton = page.locator(".calkit-play-button").first()
    await expect(playButton).toBeVisible({ timeout: 5000 })

    await playButton.click()

    // Wait for execution to start (button should show spinner)
    await page.waitForSelector(".calkit-play-button .calkit-spinner", {
      timeout: 5000,
    })

    // Wait for execution to complete (spinner disappears)
    await page.waitForSelector(
      ".calkit-play-button:not(:has(.calkit-spinner))",
      { timeout: 60000 },
    )

    // Step 6: Verify the stage ran successfully
    // Switch to sidebar to check pipeline status
    const pipelineSectionHeader = page.locator(
      '.calkit-sidebar-section-header:has-text("Pipeline")',
    )

    // Expand pipeline section if needed
    const pipelineExpanded = await pipelineSectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (pipelineExpanded === 0) {
      await pipelineSectionHeader.click()
      await page.waitForTimeout(500)
    }

    // Find the test stage
    const testStageItem = page.locator('.calkit-stage-item:has-text("test-stage")')
    await expect(testStageItem).toBeVisible({ timeout: 5000 })

    // Verify stage is not stale (successfully ran)
    const staleStage = page.locator('.calkit-stage-item.stale:has-text("test-stage")')
    const isStale = await staleStage.count()
    expect(isStale).toBe(0)

    // Verify output file was created by checking git status
    // The file should appear in the save/sync section
    const historySectionHeader = page.locator(
      '.calkit-sidebar-section-header:has-text("Save/sync")',
    )
    const historyExpanded = await historySectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (historyExpanded === 0) {
      await historySectionHeader.click()
      await page.waitForTimeout(500)
    }

    // Look for output.txt in the file list
    const outputFile = page.locator('.calkit-git-file-row:has-text("output.txt")')
    await expect(outputFile).toBeVisible({ timeout: 5000 })
  })
})
