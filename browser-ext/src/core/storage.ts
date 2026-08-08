import { DEFAULT_HUB_NAME, getHub, type Hub } from "./hubs";

export interface Credentials {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch milliseconds after which the access token needs refreshing. */
  expiresAt: number;
}

export interface Settings {
  /** Hub used by default for every surface, e.g. "production". */
  hubName: string;
  customHub: Hub | null;
  /**
   * The project being worked on, as ``owner/name``, per hub API URL.
   *
   * One at a time is deliberate: a thesis-scale monorepo is the pattern
   * this is built around, and a single active project is also what keeps
   * reference lookups fast, since each project has to be read server side
   * to search its collections. It's stored per hub because a project only
   * exists on the hub it lives on, so switching hubs must not carry a
   * project that isn't there.
   */
  activeProjects: Record<string, string>;
}

/** Settings as a surface sees them, with the current hub resolved. */
export interface SettingsView {
  hubName: string;
  customHub: Hub | null;
  hub: Hub;
  activeProject: string | null;
}

export interface SettingsUpdate {
  hubName?: string;
  customHub?: Hub | null;
  /** Applied to whichever hub is active once the update is done. */
  activeProject?: string | null;
}

const SETTINGS_KEY = "settings";
const CREDENTIALS_KEY = "credentials";
const EMAILS_KEY = "knownEmails";

export const DEFAULT_SETTINGS: Settings = {
  hubName: DEFAULT_HUB_NAME,
  customHub: null,
  activeProjects: {},
};

export async function getSettings(): Promise<Settings> {
  const stored = await chrome.storage.local.get(SETTINGS_KEY);
  return { ...DEFAULT_SETTINGS, ...(stored[SETTINGS_KEY] ?? {}) };
}

export async function getSettingsView(): Promise<SettingsView> {
  const settings = await getSettings();
  const hub = getHub(settings.hubName, settings.customHub);
  return {
    hubName: settings.hubName,
    customHub: settings.customHub,
    hub,
    activeProject: settings.activeProjects[hub.apiUrl] ?? null,
  };
}

export async function setSettings(
  update: SettingsUpdate,
): Promise<SettingsView> {
  const current = await getSettings();
  const settings: Settings = {
    ...current,
    ...(update.hubName === undefined ? {} : { hubName: update.hubName }),
    ...(update.customHub === undefined ? {} : { customHub: update.customHub }),
  };
  if (update.activeProject !== undefined) {
    // Resolved against the hub this update leaves in place, so setting the
    // hub and the project together lands the project on the new hub
    const hub = getHub(settings.hubName, settings.customHub);
    const activeProjects = { ...settings.activeProjects };
    if (update.activeProject === null) {
      delete activeProjects[hub.apiUrl];
    } else {
      activeProjects[hub.apiUrl] = update.activeProject;
    }
    settings.activeProjects = activeProjects;
  }
  await chrome.storage.local.set({ [SETTINGS_KEY]: settings });
  return getSettingsView();
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

/**
 * Who was last seen signed in to a hub, remembered per hub.
 *
 * Cached so anything that only needs to know who the user is, such as
 * deciding which hubs to offer, doesn't cost a request every time a panel
 * opens. Refreshed whenever the signed-in state is genuinely checked.
 */
export async function getKnownEmail(apiUrl: string): Promise<string | null> {
  const stored = await chrome.storage.local.get(EMAILS_KEY);
  return (stored[EMAILS_KEY] ?? {})[apiUrl] ?? null;
}

export async function setKnownEmail(
  apiUrl: string,
  email: string | null,
): Promise<void> {
  const stored = await chrome.storage.local.get(EMAILS_KEY);
  const emails: Record<string, string> = stored[EMAILS_KEY] ?? {};
  if (email === null) {
    delete emails[apiUrl];
  } else {
    emails[apiUrl] = email;
  }
  await chrome.storage.local.set({ [EMAILS_KEY]: emails });
}
