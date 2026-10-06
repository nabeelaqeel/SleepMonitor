# ── Stage 1: install all dependencies ─────────────────────────
FROM node:22-alpine AS deps

WORKDIR /app

# Copy lockfiles first — Docker caches this layer until they change
COPY package.json package-lock.json ./
RUN npm ci --frozen-lockfile


# ── Stage 2: compile TypeScript ───────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# Prune devDependencies — only ship what production needs
RUN npm ci --frozen-lockfile --omit=dev


# ── Stage 3: production runtime ───────────────────────────────
FROM node:22-alpine AS runtime

LABEL maintainer="nabeelaqeel67@gmail.com"
LABEL service="sleep-monitor-backend-api"
LABEL description="Node.js Express REST API for Sleep Monitor (Phase 2)"

# Non-root user
RUN addgroup -S apigroup && adduser -S apiuser -G apigroup

WORKDIR /app

# Only copy compiled output and pruned production node_modules
COPY --from=builder --chown=apiuser:apigroup /app/dist        ./dist
COPY --from=builder --chown=apiuser:apigroup /app/node_modules ./node_modules
COPY --from=builder --chown=apiuser:apigroup /app/package.json ./package.json

USER apiuser

ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

# Healthcheck: hit the /health endpoint which also probes the DB connection
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD wget -qO- http://localhost:3000/health || exit 1

CMD ["node", "dist/index.js"]
