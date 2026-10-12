const apiUrl = process.env.API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @atlas/shared ships raw TypeScript, so Next has to compile it.
  transpilePackages: ["@atlas/shared"],
  // The proxy below gives a request 30 seconds by default. An answer from the
  // model regularly takes longer than that, so allow ten minutes.
  experimental: {
    proxyTimeout: 600_000,
  },
  // The browser only talks to this origin; /api/* is proxied to the FastAPI service.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
