import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const apiClient = Object.assign(vi.fn(), {
    interceptors: {
      response: {
        use: vi.fn(),
      },
    },
  });
  const unversionedClient = {
    post: vi.fn(),
  };

  return { apiClient, unversionedClient };
});

vi.mock('axios', () => ({
  default: {
    create: vi.fn((config: { baseURL?: string }) =>
      config.baseURL === '/api' ? mocks.unversionedClient : mocks.apiClient,
    ),
  },
}));

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

describe('apiClient refresh handling', () => {
  beforeEach(() => {
    mocks.apiClient.mockReset();
    mocks.unversionedClient.post.mockReset();
  });

  it('shares one refresh request between concurrent eligible 401 responses', async () => {
    const [, reject] = mocks.apiClient.interceptors.response.use.mock.calls[0];
    const refresh = Promise.withResolvers<void>();
    mocks.unversionedClient.post.mockReturnValue(refresh.promise);
    mocks.apiClient.mockImplementation((config) => Promise.resolve(config));

    const firstConfig = { url: '/scanner/runs' };
    const secondConfig = { url: '/scanner/configs' };
    const firstRetry = reject({ response: { status: 401 }, config: firstConfig });
    const secondRetry = reject({ response: { status: 401 }, config: secondConfig });

    expect(mocks.unversionedClient.post).toHaveBeenCalledOnce();

    refresh.resolve();

    await Promise.all([firstRetry, secondRetry]);

    expect(mocks.apiClient).toHaveBeenCalledWith(firstConfig);
    expect(mocks.apiClient).toHaveBeenCalledWith(secondConfig);
  });
});
