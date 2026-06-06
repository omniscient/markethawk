import '@testing-library/jest-dom';

// jsdom doesn't define Notification; ChannelConfigPanel reads Notification.permission at render time
Object.defineProperty(globalThis, 'Notification', {
  value: { permission: 'default' },
  writable: true,
  configurable: true,
});
