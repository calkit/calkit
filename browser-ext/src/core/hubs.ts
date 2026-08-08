export interface Hub {
  /** Identifier stored in settings. */
  name: string;
  label: string;
  /** Base URL of the web app, e.g. where sign-in happens. */
  webUrl: string;
  /** Base URL of the API. */
  apiUrl: string;
}

// A hub's API URL isn't derivable from its web URL by any convention, so
// both are declared for each built-in instance, matching calkit.hub in the
// Python package.
export const HUBS: Record<string, Hub> = {
  production: {
    name: "production",
    label: "calkit.io",
    webUrl: "https://calkit.io",
    apiUrl: "https://api.calkit.io",
  },
  staging: {
    name: "staging",
    label: "staging.calkit.io",
    webUrl: "https://staging.calkit.io",
    apiUrl: "https://api.staging.calkit.io",
  },
  local: {
    name: "local",
    label: "Local development",
    webUrl: "http://localhost:5173",
    apiUrl: "http://api.localhost",
  },
};

export const DEFAULT_HUB_NAME = "production";

/**
 * Derive a hub's API base URL from its web URL.
 *
 * A hub serves its API from the ``api`` subdomain of the host serving its
 * web app, so a hub URL is all that's needed to find its API. This mirrors
 * ``calkit.hub.api_url_from_hub_url`` in the Python package. The built-in
 * instances are declared explicitly above, since local development
 * predates the rule and doesn't follow it.
 */
export function apiUrlFromHubUrl(hubUrl: string): string {
  const trimmed = hubUrl.trim();
  const withScheme = /^https?:\/\//.test(trimmed)
    ? trimmed
    : `${/^(localhost|127\.)/.test(trimmed) ? "http" : "https"}://${trimmed}`;
  const parsed = new URL(withScheme);
  if (!parsed.hostname) {
    throw new Error(`Cannot determine the API URL for hub '${hubUrl}'`);
  }
  // A hub URL that already names the API host is taken as-is, so a
  // mistakenly-doubled prefix (api.api.example.edu) can't happen
  const host = parsed.hostname.startsWith("api.")
    ? parsed.hostname
    : `api.${parsed.hostname}`;
  return `${parsed.protocol}//${host}${parsed.port ? `:${parsed.port}` : ""}`;
}

/** Build a custom hub entry from just its web URL. */
export function customHubFromUrl(hubUrl: string): Hub {
  const apiUrl = apiUrlFromHubUrl(hubUrl);
  const webUrl = hubUrl.trim().replace(/\/+$/, "");
  return {
    name: "custom",
    label: new URL(apiUrl).hostname.replace(/^api\./, ""),
    webUrl: /^https?:\/\//.test(webUrl) ? webUrl : `https://${webUrl}`,
    apiUrl,
  };
}

export function getHub(name: string, custom?: Hub | null): Hub {
  if (name === "custom" && custom) {
    return custom;
  }
  const hub = HUBS[name];
  if (!hub) {
    // Falling back keeps the extension usable, but silently means a hub the
    // user thinks they selected would be served by the default one, using
    // the default one's credentials. Say so rather than hiding it.
    console.warn(
      `Calkit: unknown hub '${name}'; falling back to ${DEFAULT_HUB_NAME}`,
    );
    return HUBS[DEFAULT_HUB_NAME];
  }
  return hub;
}
