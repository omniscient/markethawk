import { describe, it, expect } from 'vitest';
import { wsUrl } from './client';

describe('wsUrl', () => {
  it('generates ws:// URL from relative API_BASE', () => {
    // jsdom environment: window.location.protocol = 'http:', host = 'localhost:3000'
    // VITE_API_BASE_URL is undefined in test → API_BASE falls back to '/api/v1'
    const host = window.location.host;
    expect(wsUrl('/scanner/ws/runs/abc')).toBe(`ws://${host}/api/v1/scanner/ws/runs/abc`);
  });

  it('includes dynamic path segments', () => {
    const host = window.location.host;
    expect(wsUrl('/live/ws/AAPL/minute')).toBe(`ws://${host}/api/v1/live/ws/AAPL/minute`);
  });
});
