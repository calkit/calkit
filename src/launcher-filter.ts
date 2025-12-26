import { ILauncher } from "@jupyterlab/launcher";
import { IDisposable } from "@lumino/disposable";
import { requestAPI } from "./request";

/**
 * Check if calkit.yaml exists in the current working directory
 */
export async function hasCalkitConfig(): Promise<boolean> {
  try {
    await requestAPI<any>("config");
    return true;
  } catch (error) {
    // If config endpoint fails, assume no calkit.yaml
    return false;
  }
}

/**
 * Get available kernel names from the server
 */
async function getAvailableKernels(): Promise<Set<string>> {
  try {
    const kernels = await requestAPI<string[]>("kernelspecs");
    return new Set(kernels);
  } catch (error) {
    console.warn("Failed to fetch available kernels:", error);
    // If we can't get the list, return empty set to hide all kernels
    return new Set();
  }
}

/**
 * Filter the launcher to only show kernels available in the project
 * This works by wrapping the launcher's add() method to intercept new items
 * and replace notebook creation commands with Calkit's dialog
 */
export async function filterLauncher(launcher: ILauncher): Promise<void> {
  // Check if calkit.yaml exists
  const hasConfig = await hasCalkitConfig();
  if (!hasConfig) {
    console.log("No calkit.yaml found, showing all kernels");
    return;
  }

  console.log("calkit.yaml found, filtering launcher kernels");

  // Get available kernels from the server
  const availableKernels = await getAvailableKernels();

  if (availableKernels.size === 0) {
    console.log(
      "No kernels available in project, hiding all notebook launchers",
    );
  } else {
    console.log("Available kernels:", Array.from(availableKernels));
  }

  // Store the original add method
  const originalAdd = launcher.add.bind(launcher);

  // Wrap the add method to filter items
  launcher.add = (options: ILauncher.IItemOptions): IDisposable => {
    // Hide all notebook category items - users must use Calkit menu
    if (options.category === "Notebook") {
      console.log(`Hiding notebook launcher: ${options.command}`);
      // Return a no-op disposable
      return {
        dispose: () => {
          // Do nothing
        },
        isDisposed: false,
      };
    }
    // For all other items, or modified notebook items, add normally
    return originalAdd(options);
  };
}
