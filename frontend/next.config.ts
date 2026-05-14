import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/ws",
        destination: `${process.env.WS_BACKEND_URL ?? "http://localhost:8080"}/ws`,
      },
    ];
  },
};

export default nextConfig;
