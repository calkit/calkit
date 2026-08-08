import { getCredentials, getCurrentHub, setCredentials } from "./storage";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Raised when nobody is signed in, or the stored session can't be renewed. */
export class NotSignedInError extends ApiError {
  constructor(message = "Not signed in") {
    super(401, message);
    this.name = "NotSignedInError";
  }
}

// Refresh a little before the token actually expires, so a request doesn't
// go out with a token that dies in flight.
const REFRESH_MARGIN_MS = 30_000;

interface TokenResponse {
  access_token: string;
  refresh_token?: string | null;
  expires_in?: number | null;
}

async function readError(resp: Response): Promise<string> {
  try {
    const body = await resp.json();
    if (typeof body?.detail === "string") {
      return body.detail;
    }
    if (Array.isArray(body?.detail) && body.detail.length) {
      return body.detail.map((d: { msg?: string }) => d.msg).join(", ");
    }
  } catch {
    // Fall through to the status text below
  }
  return resp.statusText || `Request failed with status ${resp.status}`;
}

/**
 * Exchange a refresh token for a fresh pair, returning the new access token.
 *
 * The hub rotates refresh tokens, so the new one has to be stored even when
 * the caller only wanted the access token.
 */
async function refreshCredentials(apiUrl: string): Promise<string> {
  const credentials = await getCredentials(apiUrl);
  if (!credentials?.refreshToken) {
    throw new NotSignedInError();
  }
  const resp = await fetch(`${apiUrl}/login/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: credentials.refreshToken }),
  });
  if (!resp.ok) {
    // A refresh token that the hub rejects is never going to work again, so
    // drop it rather than retrying with it on every request.
    await setCredentials(apiUrl, null);
    throw new NotSignedInError(await readError(resp));
  }
  const token = (await resp.json()) as TokenResponse;
  await setCredentials(apiUrl, {
    accessToken: token.access_token,
    refreshToken: token.refresh_token ?? credentials.refreshToken,
    expiresAt: Date.now() + (token.expires_in ?? 1800) * 1000,
  });
  return token.access_token;
}

async function getAccessToken(apiUrl: string): Promise<string> {
  const credentials = await getCredentials(apiUrl);
  if (!credentials) {
    throw new NotSignedInError();
  }
  if (credentials.expiresAt - REFRESH_MARGIN_MS > Date.now()) {
    return credentials.accessToken;
  }
  return refreshCredentials(apiUrl);
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  query?: Record<
    string,
    string | string[] | number | boolean | undefined | null
  >;
  body?: unknown;
  /** Send as multipart/form-data rather than JSON. */
  form?: Record<string, string | Blob>;
  /** Make the request without credentials, e.g. during sign-in. */
  anonymous?: boolean;
}

function buildUrl(
  apiUrl: string,
  path: string,
  query: RequestOptions["query"],
): string {
  const url = new URL(apiUrl + path);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        url.searchParams.append(key, String(item));
      }
    } else {
      url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

/**
 * Call the hub API, attaching (and renewing) the stored credentials.
 *
 * This only ever runs in the service worker: the extension holds host
 * permissions for the hub, so its requests aren't subject to the page's CORS
 * rules, and the token never has to be exposed to a content script.
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const hub = await getCurrentHub();
  const url = buildUrl(hub.apiUrl, path, options.query);
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (options.form) {
    const formData = new FormData();
    for (const [key, value] of Object.entries(options.form)) {
      formData.append(key, value);
    }
    body = formData;
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const send = async (token: string | null): Promise<Response> => {
    const allHeaders: Record<string, string> = { ...headers };
    if (token) {
      allHeaders.Authorization = `Bearer ${token}`;
    }
    return fetch(url, {
      method: options.method ?? "GET",
      headers: allHeaders,
      body,
    });
  };
  let token: string | null = null;
  if (!options.anonymous) {
    token = await getAccessToken(hub.apiUrl);
  }
  let resp = await send(token);
  // A token can be rejected even when it looks unexpired, e.g. it was
  // revoked, so retry once with a freshly minted one before giving up.
  if (resp.status === 401 && !options.anonymous) {
    token = await refreshCredentials(hub.apiUrl);
    resp = await send(token);
  }
  if (!resp.ok) {
    const detail = await readError(resp);
    if (resp.status === 401 || resp.status === 403) {
      throw new NotSignedInError(detail);
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export { refreshCredentials };
