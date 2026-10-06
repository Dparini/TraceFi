import { defineConfig } from 'vite';
export default defineConfig({
  build: {outDir: '../tracefi/web', emptyOutDir: true},
  server: {proxy: {'/api': {target: 'http://127.0.0.1:8765', changeOrigin: true}}}
});
