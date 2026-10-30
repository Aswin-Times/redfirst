/**
 * Host-header allow-list for the web UI's server. The UI proxies /api/* to the backend and the
 * proxy rewrites the Host header to the backend's address, so the backend's own Host check
 * never sees what the browser sent. This check therefore has to happen here, before the
 * request is forwarded. It stops DNS-rebinding pages from reading the unauthenticated API
 * through the UI; it is not authentication.
 */

const DEFAULT_HOSTS = ["localhost", "127.0.0.1"];

/** Parse REDFIRST_ALLOWED_HOSTS: the backend's JSON list, or a comma-separated list. */
export function parseAllowedHosts(value: string | undefined): string[] {
  const raw = value?.trim();
  if (!raw) return DEFAULT_HOSTS;
  let items: unknown;
  if (raw.startsWith("[")) {
    try {
      items = JSON.parse(raw);
    } catch {
      return DEFAULT_HOSTS;
    }
  } else {
    items = raw.split(",");
  }
  if (!Array.isArray(items)) return DEFAULT_HOSTS;
  const hosts = items
    .filter((h): h is string => typeof h === "string")
    .map((h) => h.trim().toLowerCase())
    .filter(Boolean);
  return hosts.length ? hosts : DEFAULT_HOSTS;
}

/** True if the Host header's hostname (port ignored) is in the allow-list. */
export function isAllowedHost(hostHeader: string | null, allowed: string[]): boolean {
  if (!hostHeader) return false;
  const host = hostHeader.trim().toLowerCase().split(":")[0];
  return allowed.includes(host);
}
