/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vitejs.dev/config/

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    host: "0.0.0.0",
    // 代理后端API，开发时避免跨域问题
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        // 知识库大文件上传，避免开发代理先于客户端断开
        timeout: 1200_000,
      },
    },
  },
  esbuild: {
    jsx: "automatic",
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./test/setup.ts"],
    include: ["test/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    server: {
      deps: {
        inline: ["react-markdown", "rehype-sanitize", "remark-gfm"],
      },
    },
  },
});
