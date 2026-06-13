import { describe, it, expect } from 'vitest';
import { safeExternalUrl } from './url';

const TWEET_HOSTS = ['twitter.com', 'x.com', 't.co'];

describe('safeExternalUrl', () => {
  it('returns null for null input', () => {
    expect(safeExternalUrl(null)).toBeNull();
  });

  it('returns null for undefined input', () => {
    expect(safeExternalUrl(undefined)).toBeNull();
  });

  it('returns null for empty string', () => {
    expect(safeExternalUrl('')).toBeNull();
  });

  it('returns null for a javascript: scheme URL', () => {
    expect(safeExternalUrl('javascript:alert(1)')).toBeNull();
  });

  it('returns null for an http: URL (non-https)', () => {
    expect(safeExternalUrl('http://example.com/article')).toBeNull();
  });

  it('returns null for a malformed URL', () => {
    expect(safeExternalUrl('not-a-url')).toBeNull();
  });

  it('returns the URL for a valid https: URL (no allowlist)', () => {
    expect(safeExternalUrl('https://example.com/article')).toBe('https://example.com/article');
  });

  it('returns the URL for a valid https: news URL with query params', () => {
    const url = 'https://news.publisher.com/story?id=123&ref=poly';
    expect(safeExternalUrl(url)).toBe(url);
  });

  it('returns null for off-allowlist host with allowedHosts set', () => {
    expect(safeExternalUrl('https://evil.com/redirect', { allowedHosts: TWEET_HOSTS })).toBeNull();
  });

  it('accepts twitter.com with allowedHosts', () => {
    const url = 'https://twitter.com/user/status/123';
    expect(safeExternalUrl(url, { allowedHosts: TWEET_HOSTS })).toBe(url);
  });

  it('accepts x.com with allowedHosts', () => {
    const url = 'https://x.com/user/status/456';
    expect(safeExternalUrl(url, { allowedHosts: TWEET_HOSTS })).toBe(url);
  });

  it('accepts t.co with allowedHosts', () => {
    const url = 'https://t.co/abc123';
    expect(safeExternalUrl(url, { allowedHosts: TWEET_HOSTS })).toBe(url);
  });

  it('rejects http: even when host is in allowedHosts', () => {
    expect(safeExternalUrl('http://twitter.com/foo', { allowedHosts: TWEET_HOSTS })).toBeNull();
  });
});
