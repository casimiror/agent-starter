import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Vite runs this file in Node; declared here instead of pulling in @types/node for one variable.
declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  plugins: [react()],
  // In dev the UI runs on :5173 and forwards API calls to FastAPI (the `api` compose service);
  // in prod FastAPI serves dist/.
  server: { proxy: { "/api": process.env.API_PROXY_TARGET ?? "http://localhost:8000" } },
});
