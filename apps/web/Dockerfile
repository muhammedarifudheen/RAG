# The Atlas web image.
#
# Build from the repo root. API_URL is required and is fixed into the build:
# Next.js resolves the /api proxy target when it builds, not when it starts.
#   docker build -f apps/web/Dockerfile --build-arg API_URL=https://api.example.com -t atlas-web .
FROM node:22-slim

ENV NEXT_TELEMETRY_DISABLED=1
# Uses the pnpm version named by "packageManager" in the root package.json.
RUN corepack enable

WORKDIR /repo

# Manifests first, so the dependency layer is reused until they change.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/shared/package.json packages/shared/
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile

COPY packages/shared packages/shared
COPY apps/web apps/web

ARG API_URL
RUN test -n "$API_URL" || (echo "API_URL build argument is required" >&2 && exit 1)
ENV API_URL=$API_URL
RUN pnpm --filter @atlas/web build && chown -R node:node apps/web/.next

USER node
ENV NODE_ENV=production \
    PORT=8080
EXPOSE 8080

WORKDIR /repo/apps/web
CMD ["sh", "-c", "exec node node_modules/next/dist/bin/next start -H 0.0.0.0 -p ${PORT}"]
