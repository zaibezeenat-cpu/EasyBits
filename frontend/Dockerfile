# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Frontend (Next.js 16, standalone output). Multi-stage: bun installs + builds,
# a slim node image runs the tiny standalone bundle. No dev deps ship.
# ---------------------------------------------------------------------------

FROM oven/bun:1 AS builder
WORKDIR /app

# Install with the committed lockfile only -- reproducible, no surprise upgrades.
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY . .

# NEXT_PUBLIC_* is inlined into the client bundle at BUILD time, so the API URL
# must be set here, not at runtime. Empty default = same-origin: the browser
# calls "/api/..." and Caddy routes it to the backend. Override with
# --build-arg NEXT_PUBLIC_API_URL=https://api.example.com only for a split host.
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_TELEMETRY_DISABLED=1

RUN bun run build

# --- runner ----------------------------------------------------------------
FROM node:22-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Never run the server as root.
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001

# The standalone build carries its own minimal node_modules + server.js.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# Liveness: the app is up when the login page responds.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]
