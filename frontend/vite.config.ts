import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(async () => {
  const plugins = [react(), tailwindcss()];

  if (process.env.ANALYZE === 'true') {
    const { visualizer } = await import('rollup-plugin-visualizer');
    plugins.push(visualizer({ open: true, filename: 'stats.html' }) as never);
  }

  return {
    plugins,
    server: {
      port: 3333,
      watch: {
        usePolling: true,
      },
      proxy: {
        '/api': {
          target: process.env.VITE_API_TARGET || 'http://backend:8000',
          changeOrigin: true,
          ws: true,
        }
      }
    },
    build: {
      outDir: 'dist',
      sourcemap: true
    }
  };
})
