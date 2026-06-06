# NovaSight frontend — build the SPA, serve it with nginx, and reverse-proxy /api
# to the API service so the whole app is one origin (no CORS, one published port).
#
# Runtime config (apiBaseUrl) is written into config.js at container start from the
# API_BASE_URL env var (golden rule 1: nothing environment-specific baked into the
# bundle). Authentication is via the in-app login — no token in config.

# ---- Build stage ----
FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# ---- Runtime stage ----
FROM nginx:1.27-alpine AS runtime
# Single-origin server config (static SPA + /api reverse proxy).
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
# Built assets.
COPY --from=build /app/dist /usr/share/nginx/html
# Generate config.js from env on startup (nginx runs /docker-entrypoint.d/* first).
COPY docker/40-config-js.sh /docker-entrypoint.d/40-config-js.sh
RUN chmod +x /docker-entrypoint.d/40-config-js.sh
EXPOSE 80
