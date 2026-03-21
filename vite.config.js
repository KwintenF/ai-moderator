import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
const env = loadEnv(mode, process.cwd(), "");
return {
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api/anthropic": {
        target: "https://api.anthropic.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/anthropic/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("x-api-key", env.ANTHROPIC_API_KEY);
            proxyReq.setHeader("anthropic-version", "2023-06-01");
            proxyReq.setHeader("anthropic-dangerous-direct-browser-access", "true");
          });
        },
      },
      "/api/openai": {
        target: "https://api.openai.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/openai/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("Authorization", `Bearer ${env.OPENAI_API_KEY}`);
          });
        },
      },
      "/api/mistral": {
        target: "https://api.mistral.ai",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/mistral/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("Authorization", `Bearer ${env.MISTRAL_API_KEY}`);
          });
        },
      },
      "/api/runpod": {
        target: env.RUNPOD_ENDPOINT_URL || "https://api.runpod.ai",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/runpod/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq) => {
            proxyReq.setHeader("Authorization", `Bearer ${env.RUNPOD_API_KEY}`);
          });
        },
      },
    },
  },
};
});
