const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    // The default is 30 s. Reading a document or filling a form can take longer on a small server.
    proxyTimeout: 150_000,
  },
  async headers() {
    const security = [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "SAMEORIGIN" },
      { key: "Permissions-Policy", value: "microphone=(self), camera=(self), geolocation=()" },
    ];
    return [
      { source: "/:path*", headers: security },
      // ONNX Runtime and the UniOCR bundle are large and change only with a release.
      { source: "/ort/:file*", headers: [{ key: "Cache-Control", value: "public, max-age=604800" }] },
      { source: "/models/:file*", headers: [{ key: "Cache-Control", value: "public, max-age=86400" }] },
    ];
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
