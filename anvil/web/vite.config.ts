import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The built SPA is emitted straight into the FastAPI static dir so the API serves it
// same-origin in prod (cookies just work, no CORS). In dev, `vite` proxies the API to :8000.
//
// NOTE: the PWA service worker (vite-plugin-pwa) was deliberately removed. It precached the
// SPA shell and registered a NavigationRoute that hijacked every navigation — including the
// full-page Upstox OAuth return to `/?broker=...`. After connecting a broker the browser was
// served the *precached* (old) shell instead of the live one, stranding users on an old,
// tab-less "demo" build. A live market-data app must never be pinned to a cached shell, so we
// serve everything fresh from the server. The server also ships a kill-switch at /sw.js that
// unregisters any worker left over from an earlier build (see anvil/api/app.py).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/auth": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "../anvil/api/static",
    emptyOutDir: true,
  },
});
