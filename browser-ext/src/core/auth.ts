import { NotSignedInError, request } from "./api";
import type { Hub } from "./hubs";
import {
  getCredentials,
  getCurrentHub,
  setCredentials,
  setKnownEmail,
} from "./storage";
import type { UserPublic } from "./types";

interface DeviceAuthResponse {
  device_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

interface DeviceTokenResponse {
  access_token?: string;
  refresh_token?: string | null;
  expires_in?: number | null;
  detail?: string;
}

export interface AuthState {
  signedIn: boolean;
  user: UserPublic | null;
  hubLabel: string;
  hubWebUrl: string;
}

let signInInFlight: Promise<AuthState> | null = null;

/**
 * Sign in with the hub's device authorization flow, the same one the CLI
 * uses: ask for a device code, send the user to the hub to approve it, then
 * poll until the hub hands over a token pair.
 */
export async function signIn(hub?: Hub): Promise<AuthState> {
  // Two clicks on Sign in shouldn't start two flows and open two tabs
  if (signInInFlight) {
    return signInInFlight;
  }
  signInInFlight = runSignIn(hub).finally(() => {
    signInInFlight = null;
  });
  return signInInFlight;
}

async function runSignIn(requested?: Hub): Promise<AuthState> {
  const hub = requested ?? (await getCurrentHub());
  const auth = await request<DeviceAuthResponse>("/login/device", {
    method: "POST",
    body: { hostname: "Chrome extension" },
    anonymous: true,
    hub,
  });
  const tab = await chrome.tabs.create({ url: auth.verification_uri });
  // An abandoned sign-in would otherwise keep polling for the full
  // expiry window, and every request resets the service worker's idle
  // timer, so the worker stays alive and busy long after the user has
  // moved on. Closing the tab is how they say they're done.
  let abandoned = false;
  const onTabClosed = (closedTabId: number) => {
    if (closedTabId === tab.id) {
      abandoned = true;
    }
  };
  chrome.tabs.onRemoved.addListener(onTabClosed);
  try {
    return await pollForToken(hub.apiUrl, auth, () => abandoned);
  } finally {
    chrome.tabs.onRemoved.removeListener(onTabClosed);
  }
}

async function pollForToken(
  apiUrl: string,
  auth: DeviceAuthResponse,
  isAbandoned: () => boolean,
): Promise<AuthState> {
  const deadline = Date.now() + auth.expires_in * 1000;
  const intervalMs = Math.max(auth.interval, 1) * 1000;
  // Closing the tab the instant Authorize is clicked can beat the hub
  // recording it, so a closed tab buys a couple more polls rather than an
  // immediate verdict. Getting this wrong tells someone their sign-in was
  // cancelled moments after they watched it succeed.
  const POLLS_AFTER_CLOSE = 2;
  let pollsSinceClose = 0;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    // Always ask before concluding anything. Closing the tab right after
    // approving is the ordinary way to finish, so a closed tab on its own
    // says nothing; only a closed tab plus a hub that still reports the
    // request as pending means the user walked away.
    const resp = await fetch(`${apiUrl}/login/device/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: auth.device_code }),
    });
    if (resp.status === 202) {
      if (isAbandoned() && pollsSinceClose >= POLLS_AFTER_CLOSE) {
        throw new Error("Sign-in was cancelled");
      }
      if (isAbandoned()) {
        pollsSinceClose += 1;
      }
      continue;
    }
    if (!resp.ok) {
      throw new Error(
        `Sign-in failed: ${(await resp.json())?.detail ?? resp.statusText}`,
      );
    }
    const token = (await resp.json()) as DeviceTokenResponse;
    if (!token.access_token) {
      continue;
    }
    await setCredentials(apiUrl, {
      accessToken: token.access_token,
      refreshToken: token.refresh_token ?? null,
      expiresAt: Date.now() + (token.expires_in ?? 1800) * 1000,
    });
    return getAuthState();
  }
  throw new Error("Timed out waiting for authorization; try signing in again");
}

export async function signOut(): Promise<AuthState> {
  const hub = await getCurrentHub();
  await setCredentials(hub.apiUrl, null);
  await setKnownEmail(hub.apiUrl, null);
  return getAuthState();
}

export async function getAuthState(requested?: Hub): Promise<AuthState> {
  const hub = requested ?? (await getCurrentHub());
  const base = {
    signedIn: false,
    user: null,
    hubLabel: hub.label,
    hubWebUrl: hub.webUrl,
  };
  if (!(await getCredentials(hub.apiUrl))) {
    await setKnownEmail(hub.apiUrl, null);
    return base;
  }
  try {
    const user = await request<UserPublic>("/user", { hub });
    await setKnownEmail(hub.apiUrl, user.email);
    return { ...base, signedIn: true, user };
  } catch (e) {
    if (e instanceof NotSignedInError) {
      await setKnownEmail(hub.apiUrl, null);
      return base;
    }
    throw e;
  }
}
