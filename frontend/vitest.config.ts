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
      // Spec target: 35%/25%. Intermediate milestone (issue #250): 30%/22%.
      // Actuals post-ratchet: ~30.4% stmts / ~30.7% branches / ~24.3% funcs / ~31.4% lines.
      // Thresholds = floor(actual) - 3, clamped to 30/22 floor. See issue #250.
      thresholds: {
        statements: 30,
        branches: 27,
        functions: 22,
        lines: 30,
      },
    },
  },
});
