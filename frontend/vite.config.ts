import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The FastAPI orchestrator runs on the same laptop (port 8000). Proxying keeps the phone on a
// single origin: open http://<M5-IP>:5173 and every API/media call goes through Vite.
const backend = process.env.BENCHLOG_API ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/media": { target: backend, changeOrigin: true },
    },
  },
});
