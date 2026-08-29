import { expect, test } from "@jupyterlab/galata";
import type { Locator } from "@playwright/test";

/**
 * Don't load JupyterLab webpage before running the tests.
 * This is required to ensure we capture all log messages.
 */
test.use({ autoGoto: false });

test("should emit an activation console message", async ({ page }) => {
  const logs: string[] = [];

  page.on("console", (message) => {
    logs.push(message.text());
  });

  await page.goto();

  // Activation can finish after the page itself has loaded, so poll for the
  // message rather than reading the log once and hoping it has arrived
  await expect
    .poll(
      () =>
        logs.filter((s) => s === "JupyterLab extension calkit is activated!")
          .length,
    )
    .toBe(1);
});

test.describe("Notebook pipeline workflow", () => {
  // Creating the environment installs its packages and running the stage
  // executes the notebook inside it, neither of which is quick
  test.describe.configure({ timeout: 600000 });

  test("should create environment from notebook toolbar, add stage, run, and execute pipeline", async ({
    page,
  }) => {
    // Wide enough that the notebook toolbar shows its badges rather than
    // collapsing them into an overflow menu
    await page.setViewportSize({ width: 1400, height: 900 });

    await page.goto();
    await expect(page.locator(".jp-LauncherCard").first()).toBeVisible();

    // A badge renders its dropdown into a portal on the body, so it can't be
    // found within the badge itself
    const dropdown = page.locator(".calkit-badge-dropdown");

    const badgeFor = (label: string | RegExp): Locator =>
      page.locator(".calkit-badge").filter({ hasText: label }).first();

    const openBadge = async (label: string | RegExp) => {
      const badge = badgeFor(label);
      await expect(badge).toBeVisible();
      await badge.click();
      await expect(dropdown).toBeVisible();
    };

    const dataResponse = await page.request.put("/api/contents/data.csv", {
      data: {
        type: "file",
        format: "text",
        content: "x,y\n1,10\n2,20\n3,30\n",
      },
    });
    expect(dataResponse.ok()).toBe(true);

    // Write the notebook out and open it by path. Clicking a launcher card
    // and filling in the rename dialog tests JupyterLab rather than Calkit,
    // and is what raced most often
    const notebookResponse = await page.request.put(
      "/api/contents/main.ipynb",
      {
        data: {
          type: "notebook",
          content: {
            cells: [
              {
                cell_type: "code",
                source: "",
                metadata: {},
                outputs: [],
                execution_count: null,
              },
            ],
            metadata: {
              kernelspec: { name: "python3", display_name: "Python 3" },
              language_info: { name: "python" },
            },
            nbformat: 4,
            nbformat_minor: 5,
          },
        },
      },
    );
    expect(notebookResponse.ok()).toBe(true);
    expect(await page.notebook.openByPath("main.ipynb")).toBe(true);
    await expect(page.locator(".jp-NotebookPanel")).toBeVisible();

    // Step 1: create an environment from the notebook toolbar
    await openBadge("No environment selected");
    await dropdown.locator('button:has-text("Create new environment")').click();
    const envDialog = page.locator(".calkit-environment-editor-dialog");
    await expect(envDialog).toBeVisible();
    await envDialog
      .locator('input[placeholder="ex: analysis"]')
      .fill("analytics-env");
    // Add packages as a group rather than typing them in one by one
    await envDialog
      .locator('.calkit-env-package-group-btn:has-text("PyData")')
      .click();
    // The dialog's own buttons are in JupyterLab's footer, which sits
    // outside the body widget that carries the Calkit class
    await page.locator('.jp-Dialog-footer button:has-text("Create")').click();
    // The dialog stays up until the environment has been built, which means
    // resolving and installing everything in it
    await expect(envDialog).toHaveCount(0, { timeout: 480000 });

    // The toolbar reflects the new environment once its kernel is wired up
    const envBadge = badgeFor("Environment: analytics-env");
    await expect(envBadge).toBeVisible({ timeout: 120000 });
    await expect(envBadge).not.toHaveClass(/calkit-badge-loading/, {
      timeout: 120000,
    });
    // The badge stops saying it is switching once the request comes back,
    // which is before the browser has a channel to the new kernel. Running a
    // cell in that window goes nowhere, so wait for the server to report the
    // notebook's session sitting idle in the new environment
    await expect
      .poll(
        async () => {
          const response = await page.request.get("/api/sessions");
          if (!response.ok()) {
            return null;
          }
          const session = (await response.json()).find(
            (s: { path: string }) => s.path === "main.ipynb",
          );
          if (!session?.kernel) {
            return null;
          }
          return `${session.kernel.name}|${session.kernel.execution_state}`;
        },
        { timeout: 180000 },
      )
      .toMatch(/\.analytics-env\|idle$/);

    // Step 2: put the notebook in the pipeline as a stage
    await openBadge("Not in pipeline");
    await dropdown
      .locator('input[placeholder*="ex: postprocess"]')
      .fill("analytics");
    const stageSaved = page.waitForResponse(
      (response) =>
        response.url().includes("notebook/stage") &&
        response.request().method() === "PUT",
    );
    await dropdown.locator('button:has-text("Save")').first().click();
    expect((await stageSaved).ok()).toBe(true);
    await expect(badgeFor("Stage: analytics")).toBeVisible();
    // Saving closes the dropdown, which has to happen before the next badge
    // can be reached
    await expect(dropdown).toHaveCount(0);

    // Step 3: write and run analytics code that produces a figure
    expect(
      await page.notebook.setCell(
        0,
        "code",
        [
          "import os",
          "import matplotlib.pyplot as plt",
          'os.makedirs("figures", exist_ok=True)',
          "fig, ax = plt.subplots()",
          "ax.plot([1, 2, 3], [10, 20, 30])",
          'plt.savefig("figures/plot.png")',
          "plt.close()",
        ].join("\n"),
      ),
    ).toBe(true);
    // setCell leaves the cursor in the cell, so this runs the one just
    // written. Galata's runCell would do the same but gives up on a fixed
    // wait for the status bar to read Idle, which a kernel importing a
    // plotting stack for the first time doesn't manage in time
    await page.keyboard.press("Shift+Enter");
    // The cell writes the figure through the kernel, so the file appearing
    // is what says the kernel ran it, whatever the status bar says
    await expect
      .poll(
        async () =>
          (await page.request.get("/api/contents/figures/plot.png")).status(),
        { timeout: 180000 },
      )
      .toBe(200);

    // Step 4: run the stage from the toolbar's play button
    const playButton = page.locator(".calkit-play-button").first();
    await expect(playButton).toBeVisible();
    await playButton.click();
    // The button is disabled for as long as the stage is executing, so it
    // going away and coming back is what says the run started and finished.
    // Only waiting for it to be usable would pass before the run began
    await expect(playButton).toBeDisabled();
    await expect(playButton).toBeEnabled({ timeout: 300000 });
    // A failed run reports itself in a dialog, which would otherwise sit
    // there and swallow the clicks the rest of this test makes
    await expect(page.locator(".jp-Dialog")).toHaveCount(0);

    // Step 5: declare data.csv as an input
    await openBadge(/Inputs \(/);
    await dropdown
      .locator('input[placeholder*="ex: data/raw.csv"]')
      .fill("data.csv");
    await dropdown.locator('button:has-text("Add")').click();
    await expect(dropdown.locator(".calkit-io-item")).toHaveCount(1);
    await dropdown.locator('button:has-text("Save")').click();
    await expect(badgeFor("Inputs (1)")).toBeVisible();
    await expect(dropdown).toHaveCount(0);

    // Step 6: declare the figure as an output
    await openBadge(/Outputs \(/);
    await dropdown
      .locator('input[placeholder*="ex: figures/plot.png"]')
      .fill("figures/plot.png");
    await dropdown.locator('button:has-text("Add")').click();
    await expect(dropdown.locator(".calkit-io-item")).toHaveCount(1);
    await dropdown.locator('button:has-text("Save")').click();
    await expect(badgeFor("Outputs (1)")).toBeVisible();
    await expect(dropdown).toHaveCount(0);

    // Step 7: run the whole pipeline from the sidebar
    const sidebar = page.locator(".calkit-sidebar");
    if (!(await sidebar.isVisible())) {
      await page.locator('.jp-SideBar [data-id="calkit-sidebar"]').click();
      await expect(sidebar).toBeVisible();
    }
    const pipelineHeader = sidebar
      .locator(".calkit-sidebar-section-header")
      .filter({ hasText: "Pipeline" })
      .first();
    await expect(pipelineHeader).toBeVisible();
    const runButton = pipelineHeader.locator(".calkit-sidebar-section-run");
    await expect(runButton).toBeEnabled();
    await runButton.click();
    // As with the stage, the button goes away for the duration of the run
    await expect(runButton).toBeDisabled();
    await expect(runButton).toBeEnabled({ timeout: 300000 });

    // The stage has to be there before its being up to date means anything
    const stageItem = sidebar
      .locator(".calkit-stage-item")
      .filter({ hasText: "analytics" });
    await expect(stageItem).toHaveCount(1);
    await expect(stageItem).not.toHaveClass(/stale/);
  });
});
