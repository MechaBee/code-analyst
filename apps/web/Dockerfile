# syntax=docker/dockerfile:1
FROM node:24-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package manifests
COPY apps/web/package.json ./
COPY apps/web/pnpm-lock.yaml* ./

# Install dependencies
RUN pnpm install --frozen-lockfile || pnpm install

# Copy source
COPY apps/web/tsconfig.json ./
COPY apps/web/next.config.mjs ./
COPY apps/web/tailwind.config.ts ./
COPY apps/web/postcss.config.mjs ./
COPY apps/web/next-env.d.ts ./
COPY apps/web/src ./src
COPY apps/web/server ./server
COPY apps/web/server/tsconfig.json ./server/tsconfig.json

# Build the Next.js app
RUN pnpm build

# --- Production stage ---
FROM node:24-alpine AS runner

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

ENV NODE_ENV=production
ENV PORT=3000

# Copy package manifest and install production deps only
COPY apps/web/package.json ./
COPY apps/web/pnpm-lock.yaml ./
RUN pnpm install --prod --frozen-lockfile || pnpm install --prod

# Copy built assets and runtime config
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/next.config.mjs ./next.config.mjs

EXPOSE 3000

CMD ["pnpm", "start"]
