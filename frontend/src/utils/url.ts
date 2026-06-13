interface SafeUrlOptions {
  allowedHosts?: string[];
}

/**
 * Validates an external URL for safe use in href/src attributes.
 * Returns the URL string if valid, null if it fails validation.
 * Scheme must be https:. If allowedHosts is provided, the hostname
 * must exactly match one of the entries.
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
    if (!options.allowedHosts.includes(parsed.hostname)) return null;
  }

  return url;
}
