import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Internal admin tool (§6). Separate app, NOT served on the public domain — no
// PWA, no offline. Proxies /api to the dev API server.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: { "/api": "http://localhost:3000" },
  },
});
