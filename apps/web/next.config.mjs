const apiUrl = process.env.API_URL ?? "http://localhost:8000";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @atlas/shared ships raw TypeScript, so Next has to compile it.
  transpilePackages: ["@atlas/shared"],
  // The browser only talks to this origin; /api/* is proxied to the FastAPI service.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
