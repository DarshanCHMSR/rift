import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy /run, /results, /health, /execute to the FastAPI backend.
    // This avoids CORS issues during local development and means the
    // frontend can use relative paths by setting VITE_API_BASE_URL=/
    proxy: {
      "/run": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/execute": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/results": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/health": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      "/runs": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});

