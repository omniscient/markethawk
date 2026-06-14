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
      // Host-header allowlist for the dev server. Defaults to localhost only;
      // set VITE_ALLOWED_HOSTS (comma-separated) in your local .env for any
      // reverse-proxy / tunnel / Tailscale hostnames you reach the dev server by.
      // A leading dot (e.g. ".ts.net") matches that host and all subdomains.
      allowedHosts: process.env.VITE_ALLOWED_HOSTS
        ? process.env.VITE_ALLOWED_HOSTS.split(',').map((h) => h.trim()).filter(Boolean)
        : ['localhost'],
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
