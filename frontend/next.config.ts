import type { NextConfig } from "next";

// The browser talks to the API through these same-origin rewrites, so the session cookie is
// first-party and no CORS is needed. Live video WebSockets connect to the backend directly
// (see lib/ws.ts). BACKEND_URL is read when the server/build starts.
const BACKEND_URL = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  // Hostnames (not origins) allowed to load the dev server, e.g. a LAN IP for phone streaming.
  allowedDevOrigins: (process.env.NEXT_DEV_ALLOWED_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean),
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${BACKEND_URL}/api/v1/:path*` },
      { source: "/health", destination: `${BACKEND_URL}/health` },
      { source: "/health/ready", destination: `${BACKEND_URL}/health/ready` },
    ];
  },
  async redirects() {
    // Earlier pages of this project.
    return [
      { source: "/monitoring", destination: "/live", permanent: false },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
