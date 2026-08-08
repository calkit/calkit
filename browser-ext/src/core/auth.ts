import { NotSignedInError, request } from "./api";
import { getCredentials, getCurrentHub, setCredentials } from "./storage";
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
export async function signIn(): Promise<AuthState> {
  // Two clicks on Sign in shouldn't start two flows and open two tabs
  if (signInInFlight) {
    return signInInFlight;
  }
  signInInFlight = runSignIn().finally(() => {
    signInInFlight = null;
  });
  return signInInFlight;
}

async function runSignIn(): Promise<AuthState> {
  const hub = await getCurrentHub();
  const auth = await request<DeviceAuthResponse>("/login/device", {
    method: "POST",
    body: { hostname: "Chrome extension" },
    anonymous: true,
  });
  await chrome.tabs.create({ url: auth.verification_uri });
  const deadline = Date.now() + auth.expires_in * 1000;
  const intervalMs = Math.max(auth.interval, 1) * 1000;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    const resp = await fetch(`${hub.apiUrl}/login/device/token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_code: auth.device_code }),
    });
    if (resp.status === 202) {
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
    await setCredentials(hub.apiUrl, {
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
  return getAuthState();
}

export async function getAuthState(): Promise<AuthState> {
  const hub = await getCurrentHub();
  const base = {
    signedIn: false,
    user: null,
    hubLabel: hub.label,
    hubWebUrl: hub.webUrl,
  };
  if (!(await getCredentials(hub.apiUrl))) {
    return base;
  }
  try {
    const user = await request<UserPublic>("/user");
    return { ...base, signedIn: true, user };
  } catch (e) {
    if (e instanceof NotSignedInError) {
      return base;
    }
    throw e;
  }
}
