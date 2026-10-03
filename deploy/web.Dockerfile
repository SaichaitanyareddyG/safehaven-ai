# SafeHaven nurse dashboard: built once, served as static files by Caddy.
FROM node:22-alpine AS build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
# --legacy-peer-deps: install exactly the lockfile that runs today.
# @zxing/browser 0.2.1 declares a peer of @zxing/library ^0.23 while the
# project pins 0.21.3; that pair is what the QR scanner was tested with.
# Resolve the versions properly (and re-test scanning) before relying on npm
# defaults.
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
# The dashboard calls the backend at this address (baked in at build time).
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM caddy:2-alpine
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /web/dist /srv
EXPOSE 8080
