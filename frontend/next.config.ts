import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api is proxied to FastAPI.
// One origin means the session cookie is first-party and no CORS is needed.
const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  agentRules: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    root: __dirname, // this folder, not a lockfile Next finds higher up
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
