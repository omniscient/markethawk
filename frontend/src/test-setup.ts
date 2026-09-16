import '@testing-library/jest-dom';

// jsdom doesn't define Notification; ChannelConfigPanel reads Notification.permission at render time
Object.defineProperty(globalThis, 'Notification', {
  value: { permission: 'default' },
  writable: true,
  configurable: true,
});

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
