import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev proxy: same-origin /v1 requests reach the local API without CORS.
    proxy: {
      "/v1": {
        target: process.env.VITE_AUTONOESIS_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  preview: { port: 4173 },
});
