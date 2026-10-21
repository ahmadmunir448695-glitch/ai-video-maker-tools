import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    // Proxying /api in development keeps the SPA and the API same-origin, so the
    // HttpOnly refresh cookie is sent without any CORS credential dance.
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
      "/media": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    include: ["src/**/*.spec.js"],
    globals: true,
  },
});
