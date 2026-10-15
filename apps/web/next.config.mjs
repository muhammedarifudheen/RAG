const apiUrl = process.env.API_URL ?? "http://localhost:8000";

// STATIC_EXPORT=1 builds plain files for a static host such as GitHub Pages.
// There is then no server to proxy /api, so the browser calls the API directly
// at NEXT_PUBLIC_API_URL, and BASE_PATH is the folder the site is served from
// (for GitHub Pages, "/<repository name>").
const staticExport = process.env.STATIC_EXPORT === "1";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @atlas/shared ships raw TypeScript, so Next has to compile it.
  transpilePackages: ["@atlas/shared"],
  ...(staticExport
    ? {
        output: "export",
        basePath: process.env.BASE_PATH || "",
        // /chat/ as chat/index.html, which every static host can serve.
        trailingSlash: true,
        images: { unoptimized: true },
      }
    : {
        // The proxy below gives a request 30 seconds by default. An answer from the
        // model regularly takes longer than that, so allow ten minutes.
        experimental: {
          proxyTimeout: 600_000,
        },
        // The browser only talks to this origin; /api/* is proxied to the FastAPI service.
        async rewrites() {
          return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
        },
      }),
};

export default nextConfig;
