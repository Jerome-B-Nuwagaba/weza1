import type { NextConfig } from "next";

const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Single build worker: avoids spawn limits on some Windows machines; no effect on output.
  experimental: { cpus: 1, workerThreads: false },
  // Same-origin API proxy: keeps the staff refresh-token cookie first-party (blueprint 13 §1).
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_URL.replace(/\/$/, "")}/api/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default nextConfig;
