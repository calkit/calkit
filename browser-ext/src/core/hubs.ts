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

export function getHub(name: string, custom?: Hub | null): Hub {
  if (name === "custom" && custom) {
    return custom;
  }
  return HUBS[name] ?? HUBS[DEFAULT_HUB_NAME];
}
