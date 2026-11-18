/** @type {import('next').NextConfig} */
const backend = process.env.BACKEND_URL || "http://localhost:8000";
const nextConfig = {
  output: "standalone",
  // The browser talks only to Next.js; /api is proxied to FastAPI so the session cookie is first-party.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
  experimental: { proxyTimeout: 300000 },
};
export default nextConfig;
