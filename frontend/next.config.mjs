const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // The default is 30 s. Reading a document or filling a form can take longer on a small server.
    proxyTimeout: 150_000,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/portal/:path*", destination: `${backend}/portal/:path*` },
      { source: "/static/:path*", destination: `${backend}/static/:path*` },
    ];
  },
};

export default nextConfig;
