import { send } from "./messages";

let cached: string | null = null;

// A content script outlives a hub switch, so a cached URL would keep
// pointing links at the old instance until the page was reloaded.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.settings) {
    cached = null;
  }
});

/**
 * Base URL of the web app for the configured hub, so links out of a panel
 * point at the instance the user is actually signed in to.
 */
export async function getHubWebUrl(): Promise<string> {
  if (cached === null) {
    cached = (await send({ type: "hubs.get" })).current.webUrl;
  }
  return cached;
}

export function projectUrl(
  hubWebUrl: string,
  owner: string,
  project: string,
): string {
  return `${hubWebUrl}/${owner}/${project}`;
}
