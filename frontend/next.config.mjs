/** @type {import('next').NextConfig} */
const nextConfig = {
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
