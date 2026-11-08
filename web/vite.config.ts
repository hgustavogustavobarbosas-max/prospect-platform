import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Em desenvolvimento, as chamadas /v1 vao para a API local (mesma origem em producao via nginx).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/v1": "http://localhost:8000", "/public": "http://localhost:8000" } },
});
