import { DEFAULT_HUB_NAME, getHub, type Hub } from "./hubs";

export interface Credentials {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds after which the access token needs refreshing. */
  expiresAt: number;
}

export interface Settings {
  hubName: string;
  customHub: Hub | null;
  /**
   * Projects checked when looking a reference up, as ``owner/name``. Kept
   * explicit because each one has to be read server side, so searching
   * everything the user can see would be too slow to do on page load.
   */
  watchedProjects: string[];
}

const SETTINGS_KEY = "settings";
const CREDENTIALS_KEY = "credentials";

export const DEFAULT_SETTINGS: Settings = {
  hubName: DEFAULT_HUB_NAME,
  customHub: null,
  watchedProjects: [],
};

export async function getSettings(): Promise<Settings> {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  return { ...DEFAULT_SETTINGS, ...(stored[SETTINGS_KEY] ?? {}) };
}

export async function setSettings(
  update: Partial<Settings>,
): Promise<Settings> {
  const settings = { ...(await getSettings()), ...update };
  await chrome.storage.local.set({ [SETTINGS_KEY]: settings });
  return settings;
}

export async function getCurrentHub(): Promise<Hub> {
  const settings = await getSettings();
  return getHub(settings.hubName, settings.customHub);
}

// Credentials are stored per hub so switching between, say, production and a
// local instance doesn't send one instance's token to the other.
type CredentialStore = Record<string, Credentials>;

async function readCredentialStore(): Promise<CredentialStore> {
  const stored = await chrome.storage.local.get(CREDENTIALS_KEY);
  return stored[CREDENTIALS_KEY] ?? {};
}

export async function getCredentials(
  apiUrl: string,
): Promise<Credentials | null> {
  return (await readCredentialStore())[apiUrl] ?? null;
}

export async function setCredentials(
  apiUrl: string,
  credentials: Credentials | null,
): Promise<void> {
  const store = await readCredentialStore();
  if (credentials === null) {
    delete store[apiUrl];
  } else {
    store[apiUrl] = credentials;
  }
  await chrome.storage.local.set({ [CREDENTIALS_KEY]: store });
}
