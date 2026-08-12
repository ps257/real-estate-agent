import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy các route của agent sang uvicorn. Nhờ vậy frontend gọi "/chat" tương
// đối — không hardcode host, không đụng CORS, và build production đặt sau cùng
// một reverse proxy là chạy y nguyên.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
      "/v1": "http://127.0.0.1:8000",
    },
  },
});
