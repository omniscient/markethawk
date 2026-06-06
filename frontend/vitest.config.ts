import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    coverage: {
      provider: 'v8',
      all: true,
      include: ['src/**'],
      exclude: [
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/test-setup.ts',
        'src/test-utils/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.d.ts',
      ],
      // Spec target: 35%/25%. Actual post-implementation coverage: 21.6%/21.1%/16.7%/22.3%.
      // Spec assumption: if actuals land below 35%, set honestly and file a ratchet follow-up.
      // Thresholds set ~3pp below actuals for stable CI headroom. See issue #250.
      thresholds: {
        statements: 18,
        branches: 18,
        functions: 13,
        lines: 19,
      },
    },
  },
});
