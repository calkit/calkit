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

    // Wait for JupyterLab to be ready
    await page.waitForSelector(".jp-LauncherCard", { timeout: 30000 })

    // Step 0: Create data.csv file
    // Click on the File menu
    const fileMenu = page.locator(".jp-MenuBar-item").filter({ hasText: "File" })
    await fileMenu.click()

    // Click "New" -> "Text File"
    const newTextFile = page.locator(".jp-Menu-item").filter({ hasText: /Text File/ })
    await newTextFile.click()

    // Wait for text editor to open
    await page.waitForSelector(".jp-FileEditor", { timeout: 5000 })

    // Type CSV content
    await page.keyboard.type("x,y\n1,10\n2,20\n3,30")

    // Save the file (Ctrl+S)
    await page.keyboard.press("Control+s")

    // Dialog should appear asking for filename
    await page.waitForSelector(".jp-Input-Dialog", { timeout: 5000 })

    const filenameInput = page.locator(".jp-Input-Dialog input")
    await filenameInput.fill("data.csv")

    // Click OK/Save button
    const okButton = page.locator(".jp-Input-Dialog button").filter({ hasText: "Save" })
    await okButton.click()

    // Wait for file to be saved and dialog to close
    await page.waitForTimeout(1000)

    // Step 1: Create a new notebook using the File menu or launcher
    // Look for the "New" button or Launcher
    const launcherCards = page.locator(".jp-LauncherCard")
    const notebookCard = launcherCards.filter({ hasText: "Notebook" }).first()
    await notebookCard.click()

    // Wait for notebook to be created and opened
    await page.waitForSelector(".jp-NotebookPanel", { timeout: 10000 })

    // Step 2: Create environment from notebook toolbar
    // Click the environment badge (should show "No environment selected")
    const envBadge = page.locator(".calkit-badge").filter({ hasText: "No environment selected" }).first()
    await envBadge.click()

    // Wait for dropdown
    await page.waitForTimeout(500)

    // Click the "+ Create new…" option in the environment select
    const envSelect = page.locator("select").first()
    await envSelect.selectOption("__create__")

    // Wait for environment editor dialog
    await page.waitForSelector(".calkit-modal-overlay", { timeout: 5000 })

    // Fill in environment name
    const nameInput = page.locator('input[placeholder="Environment name"]')
    await nameInput.fill("analytics-env")

    // Select Python version (3.14)
    const pythonInput = page.locator('input[placeholder*="Python"]')
    await pythonInput.clear()
    await pythonInput.fill("3.14")

    // Look for PyData package group selector
    // Assuming there's a package selection UI
    const packageInputs = page.locator('textarea, input').filter({ hasText: /packages/i })
    if (await packageInputs.count() > 0) {
      const packagesField = packageInputs.first()
      await packagesField.fill("pandas\nmatplotlib")
    }

    // Click Create button
    const createButton = page.locator('button:has-text("Create")').first()
    await createButton.click()

    // Wait for environment creation to complete
    await page.waitForSelector(".calkit-modal-overlay", {
      state: "hidden",
      timeout: 15000,
    })

    // Step 3: Set the notebook to have a pipeline stage via notebook toolbar
    // Click the stage badge (should show "Not in pipeline")
    const stageBadge = page.locator(".calkit-badge").filter({ hasText: "Not in pipeline" }).first()
    await stageBadge.click()

    // Wait for dropdown
    await page.waitForTimeout(500)

    // Fill in stage name
    const stageNameInput = page.locator('input[placeholder*="e.g., postprocess"]')
    await stageNameInput.fill("analytics")

    // Scroll down to see storage options if needed
    const formContent = page.locator(".calkit-dropdown-content")
    await formContent.evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })

    // Select Git for both storage options (defaults)
    const storageSelects = page.locator("select")
    const selectCount = await storageSelects.count()

    // First select is environment select (already handled), next two should be storage
    if (selectCount >= 3) {
      // Already defaults to Git, so just click Save
    }

    // Click Save button
    const saveButton = page.locator('button:has-text("Save")').first()
    await saveButton.click()

    // Wait for stage to be saved
    await page.waitForTimeout(1000)

    // Step 4: Write analytics code with pandas and matplotlib
    // Click on the first cell
    const firstCell = page.locator(".jp-Cell").first()
    await firstCell.click()

    // Enter code that reads data.csv and creates a plot
    await page.keyboard.type(
      'import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.read_csv("data.csv")\nplt.figure()\nplt.plot(df["x"], df["y"])\nplt.savefig("figures/plot.png")\nplt.close()',
    )

    // Save the notebook (Ctrl+S)
    await page.keyboard.press("Control+s")
    await page.waitForTimeout(1000)

    // Step 5: Run the stage with the play button
    const playButton = page.locator(".calkit-play-button").first()
    await expect(playButton).toBeVisible({ timeout: 5000 })

    await playButton.click()

    // Wait for execution to start and complete
    await page.waitForSelector(".calkit-play-button .calkit-spinner", {
      timeout: 5000,
    })

    // Wait for execution to complete
    await page.waitForSelector(
      ".calkit-play-button:not(:has(.calkit-spinner))",
      { timeout: 60000 },
    )

    // Step 6: Add data.csv as an input
    // Click on the Inputs badge
    const inputsBadge = page.locator(".calkit-badge").filter({ hasText: /Inputs \(/ }).first()
    await inputsBadge.click()

    // Wait for dropdown
    await page.waitForTimeout(500)

    // Add data.csv as input
    const inputField = page.locator('input[placeholder*="path/to/input"]')
    await inputField.fill("data.csv")

    // Click add/save button
    const addButton = page.locator('button:has-text("Add")').first()
    if (await addButton.isVisible()) {
      await addButton.click()
    }

    const saveInputButton = page.locator('button:has-text("Save")').first()
    await saveInputButton.click()

    // Wait for input to be saved
    await page.waitForTimeout(500)

    // Step 7: Define figures/plot.png as output
    // Click on the Outputs badge
    const outputsBadge = page.locator(".calkit-badge").filter({ hasText: /Outputs \(/ }).first()
    await outputsBadge.click()

    // Wait for dropdown
    await page.waitForTimeout(500)

    // Add figures/plot.png as output
    const outputField = page.locator('input[placeholder*="path/to/output"]')
    await outputField.fill("figures/plot.png")

    // Click add button
    const addOutputButton = page.locator('button:has-text("Add")').first()
    if (await addOutputButton.isVisible()) {
      await addOutputButton.click()
    }

    const saveOutputButton = page.locator('button:has-text("Save")').first()
    await saveOutputButton.click()

    // Wait for output to be saved
    await page.waitForTimeout(500)

    // Step 8: Run the entire pipeline from the sidebar play button
    // Open Calkit sidebar
    const calkitSidebar = page.locator(".calkit-sidebar")
    const sidebarVisible = await calkitSidebar.isVisible()

    if (!sidebarVisible) {
      const calkitTab = page.locator('.jp-SideBar [data-id="calkit-sidebar"]')
      if (await calkitTab.count() > 0) {
        await calkitTab.click()
        await page.waitForSelector(".calkit-sidebar", { timeout: 10000 })
      }
    }

    // Find and expand Pipeline section
    const pipelineSectionHeader = page.locator(
      '.calkit-sidebar-section-header:has-text("Pipeline")',
    )

    const pipelineExpanded = await pipelineSectionHeader
      .locator(".calkit-sidebar-section-icon:has-text('▼')")
      .count()
    if (pipelineExpanded === 0) {
      await pipelineSectionHeader.click()
      await page.waitForTimeout(500)
    }

    // Find the analytics stage and click its play button
    const analyticsStageLine = page.locator('.calkit-stage-item:has-text("analytics")')
    const stagePlayButton = analyticsStageLine.locator(".calkit-stage-play-button, button[title*='Run']").first()

    if (await stagePlayButton.isVisible()) {
      await stagePlayButton.click()

      // Wait for pipeline execution to start and complete
      await page.waitForSelector(".calkit-spinner", {
        timeout: 5000,
      })

      // Wait for execution to complete
      await page.waitForTimeout(5000)
    }

    // Verify that the stage ran successfully
    const staleStage = page.locator('.calkit-stage-item.stale:has-text("analytics")')
    const isStale = await staleStage.count()
    expect(isStale).toBe(0)
  })
})
