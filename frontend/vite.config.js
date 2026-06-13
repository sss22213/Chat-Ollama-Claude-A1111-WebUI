import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 後端位址（dev 代理目標）
const BACKEND = process.env.BACKEND_URL || "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // 用 5273 避開常見的 5173（使用者另有專案佔用）
    port: 5273,
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/images": { target: BACKEND, changeOrigin: true },
    },
  },
});
