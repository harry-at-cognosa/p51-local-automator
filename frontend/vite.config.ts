import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/static",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes("node_modules")) {
            return "vendor";
          }
        },
      },
    },
  },
  base: "/app",
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Static landing-page assets are mounted at /landing/images on the
      // backend; the Dashboard's header strip <img> tags resolve to them.
      "/landing": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
