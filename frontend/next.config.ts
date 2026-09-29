import type { NextConfig } from "next";

const backendApiUrl = (
  process.env.BACKEND_API_URL ?? "http://127.0.0.1:8001"
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  reactCompiler: true,
  // Browser requests remain same-origin; Next proxies them to FastAPI server-side.
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${backendApiUrl}/api/:path*`,
      },
    ];
  },
  // Permit the Arena live-preview origin during development.
  allowedDevOrigins: ["*.e2b.app"],
};

export default nextConfig;
