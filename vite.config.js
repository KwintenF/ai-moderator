import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
const env = loadEnv(mode, process.cwd(), "");
const debug = env.VITE_DEBUG === "true";
const log = (...args) => debug && console.log("[proxy]", ...args);

return {
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api/anthropic": {
        target: "https://api.anthropic.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/anthropic/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            log("anthropic →", req.url, "| key present:", !!env.ANTHROPIC_API_KEY);
            proxyReq.setHeader("x-api-key", env.ANTHROPIC_API_KEY);
            proxyReq.setHeader("anthropic-version", "2023-06-01");
            proxyReq.setHeader("anthropic-dangerous-direct-browser-access", "true");
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            log("anthropic ←", req.url, "| status:", proxyRes.statusCode);
          });
        },
      },
      "/api/openai": {
        target: "https://api.openai.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/openai/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            log("openai →", req.url, "| key present:", !!env.OPENAI_API_KEY);
            proxyReq.setHeader("Authorization", `Bearer ${env.OPENAI_API_KEY}`);
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            log("openai ←", req.url, "| status:", proxyRes.statusCode);
          });
        },
      },
      "/api/mistral": {
        target: "https://api.mistral.ai",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/mistral/, ""),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            log("mistral →", req.url, "| key present:", !!env.MISTRAL_API_KEY, "| length:", env.MISTRAL_API_KEY?.length);
            proxyReq.setHeader("Authorization", `Bearer ${env.MISTRAL_API_KEY}`);
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            log("mistral ←", req.url, "| status:", proxyRes.statusCode);
          });
        },
      },
      "/api/google": {
        target: "https://generativelanguage.googleapis.com",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/google/, "/v1beta/openai"),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            log("google →", req.url, "| key present:", !!env.GOOGLE_AI_KEY);
            proxyReq.setHeader("Authorization", `Bearer ${env.GOOGLE_AI_KEY}`);
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            log("google ←", req.url, "| status:", proxyRes.statusCode);
          });
        },
      },
      "/api/runpod": {
        target: env.RUNPOD_ENDPOINT_URL || "https://api.runpod.ai",
        changeOrigin: true,
        timeout: 600000,
        proxyTimeout: 600000,
        rewrite: (path) => path.replace(/^\/api\/runpod/, "/runsync"),
        configure: (proxy) => {
          proxy.on("proxyReq", (proxyReq, req) => {
            log("runpod →", req.url, "| key present:", !!env.RUNPOD_API_KEY, "| target:", env.RUNPOD_ENDPOINT_URL);
            proxyReq.setHeader("Authorization", `Bearer ${env.RUNPOD_API_KEY}`);
          });
          proxy.on("proxyRes", (proxyRes, req) => {
            log("runpod ←", req.url, "| status:", proxyRes.statusCode);
          });
        },
      },
    },
  },
};
});
