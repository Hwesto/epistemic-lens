import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// PWA-first (§1, §8): installable, offline shell. Today's story is static content
// served from a CDN; the app shell is precached so it opens offline.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.svg"],
      manifest: {
        name: "Daily Values",
        short_name: "Values",
        description: "One shared story a day. What would you do?",
        theme_color: "#0f172a",
        background_color: "#0f172a",
        display: "standalone",
        start_url: "/",
        icons: [
          { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" }
        ]
      },
      workbox: {
        // App shell precached; today's story fetched network-first then cached.
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith("/api/today"),
            handler: "NetworkFirst",
            options: { cacheName: "today-story" }
          }
        ]
      }
    })
  ],
  server: {
    proxy: {
      // local dev: forward /api to the serverless functions runtime
      "/api": "http://localhost:3000"
    }
  }
});
