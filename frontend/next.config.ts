import type { NextConfig } from "next";

// The browser only talks to this app; /api/* is proxied to the FastAPI backend, so the
// backend needs no CORS configuration and its address never reaches client code.
const backendUrl = process.env.REDFIRST_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
};

export default nextConfig;
