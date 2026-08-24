export interface Hub {
  /** Identifier stored in settings. */
  name: string;
  label: string;
  /** Base URL of the web app, e.g. where sign-in happens. */
  webUrl: string;
  /** Base URL of the API. */
  apiUrl: string;
}

// The built-in instances declare both URLs rather than deriving the API
// one with apiUrlFromHubUrl: local development predates the api-subdomain
// rule and doesn't follow it (localhost:5173 is served by api.localhost),
// and production's is a prefix of a host that also serves the web app.
// A self-hosted hub does follow the rule, which is why its URL alone is
// enough. This matches calkit.hub in the Python package.
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
 * Who sees the staging instance offered as a hub.
 *
 * Staging exists for the people who develop Calkit, and offering it to
 * everyone else invites picking it by mistake and wondering where their
 * projects went. This only decides what the pickers list: staging is a
 * public URL and gating it here is tidiness, not a security boundary.
 */
const STAGING_EMAILS = ["petebachant@gmail.com"];

/**
 * Hubs worth offering to this user.
 *
 * The hub currently in use is always included, so someone already on a
 * hub they'd no longer be offered isn't stranded on a picker that can't
 * represent where they are.
 */
export function visibleHubs(
  email: string | null,
  currentHubName: string,
): Hub[] {
  return Object.values(HUBS).filter((hub) => {
    if (hub.name === currentHubName) {
      return true;
    }
    if (hub.name === "staging") {
      return Boolean(email && STAGING_EMAILS.includes(email.toLowerCase()));
    }
    return true;
  });
}

/**
 * Derive a hub's API base URL from its web URL.
 *
 * A hub serves its API from the ``api`` subdomain of the host serving its
 * web app, so a hub URL is all that's needed to find its API. This mirrors
 * ``calkit.hub.api_url_from_hub_url`` in the Python package. The built-in
 * instances are declared explicitly above, since local development
 * predates the rule and doesn't follow it.
 */
/**
 * Whether a host is this machine, and so exempt from the https rule.
 *
 * A local development stack has no certificates, and its object storage
 * answers on its own subdomain (objects.localhost), so matching the
 * literal names isn't enough. This is the same set browsers treat as a
 * secure context over plain http.
 */
export function isLoopbackHost(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return (
    host === "localhost" ||
    host.endsWith(".localhost") ||
    host === "::1" ||
    /^127(\.\d{1,3}){3}$/.test(host)
  );
}

/**
 * Put a hub URL in the one form everything else compares against.
 *
 * calkit.yaml may carry a hub with no scheme, or with a trailing slash,
 * and a project written by the CLI and one written by hand shouldn't
 * resolve to different hubs. Local hosts get http, since they have no
 * certificates; this matches ``config.normalize_hub_url`` in the Python
 * package.
 */
export function normalizeHubUrl(hubUrl: string): string {
  const trimmed = hubUrl.trim().replace(/\/+$/, "");
  if (/^https?:\/\//.test(trimmed)) {
    return trimmed;
  }
  const local = /^(localhost|127\.)/.test(trimmed);
  return `${local ? "http" : "https"}://${trimmed}`;
}

export function apiUrlFromHubUrl(hubUrl: string): string {
  const parsed = new URL(normalizeHubUrl(hubUrl));
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

/**
 * Resolve a hub from the web URL a project declares for itself.
 *
 * A project names its hub in calkit.yaml, and that is enough to talk to
 * it: a built-in instance is matched outright, and anything else is
 * derived from the URL by the `api` subdomain rule. Reaching a hub that
 * isn't built in still needs Chrome to have granted its host, which only
 * the options page can ask for.
 */
export function resolveHubByWebUrl(webUrl: string): Hub {
  const normalized = normalizeHubUrl(webUrl);
  for (const hub of Object.values(HUBS)) {
    if (normalizeHubUrl(hub.webUrl) === normalized) {
      return hub;
    }
  }
  return unknownHub(normalized);
}

/** A hub that isn't built in: nameable, but not reachable. */
function unknownHub(webUrl: string): Hub {
  return {
    name: "unknown",
    label: hostOf(webUrl),
    webUrl,
    apiUrl: apiUrlFromHubUrl(webUrl),
  };
}

function hostOf(webUrl: string): string {
  return webUrl.replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

/** Whether a hub is one this build can actually reach. */
export function isKnownHub(hub: Hub): boolean {
  return hub.name !== "unknown";
}
