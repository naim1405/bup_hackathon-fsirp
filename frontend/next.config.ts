import type { NextConfig } from "next";

const backendApiUrl = (
  process.env.BACKEND_API_URL ?? "http://127.0.0.1:8001"
).replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Standalone output is only for our container build; Vercel uses its native adapter.
  ...(process.env.DOCKER_BUILD === "1"
    ? { output: "standalone" as const }
    : {}),
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
