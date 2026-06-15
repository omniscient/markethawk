interface SafeUrlOptions {
  allowedHosts?: string[];
}

/**
 * Validates an external URL for safe use in href/src attributes.
 * Returns the URL string if valid, null if it fails validation.
 * Scheme must be https:. If allowedHosts is provided, the hostname
 * must match an exact host or any subdomain thereof.
 */
export function safeExternalUrl(
  url: string | null | undefined,
  options: SafeUrlOptions = {}
): string | null {
  if (!url) return null;

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return null;
  }

  if (parsed.protocol !== 'https:') return null;

  if (options.allowedHosts && options.allowedHosts.length > 0) {
    const host = parsed.hostname;
    const allowed = options.allowedHosts.some(
      (h) => host === h || host.endsWith(`.${h}`)
    );
    if (!allowed) return null;
  }

  return url;
}
