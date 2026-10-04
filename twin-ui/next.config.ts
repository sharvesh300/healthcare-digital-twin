import type { NextConfig } from "next";

// The twin API (FastAPI, `uv run twin serve`). Browser REST calls go through /api/twin/* so the
// API origin stays server-side and no CORS is needed; the WebSocket connects directly
// (NEXT_PUBLIC_TWIN_WS_URL), because rewrites cannot carry a socket.
const TWIN_API_URL = process.env.TWIN_API_URL ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/twin/:path*", destination: `${TWIN_API_URL}/:path*` }];
  },
};

export default nextConfig;
