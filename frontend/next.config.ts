import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" bundles a minimal server + only the node_modules actually used,
  // so the production Docker image ships without the full dev dependency tree.
  output: "standalone",

  // Security headers on every response. The API sets its own; these cover the
  // pages Next serves. HSTS is safe here because Caddy terminates TLS in front.
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-XSS-Protection", value: "0" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
          { key: "X-DNS-Prefetch-Control", value: "off" },
        ],
      },
    ];
  },
};

export default nextConfig;
