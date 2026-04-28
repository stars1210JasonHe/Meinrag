# syntax=docker/dockerfile:1.6

# ── Stage 1: build ───────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Cache deps
COPY package*.json ./
RUN npm ci

# Source + build
COPY . .

# Empty VITE_API_URL → SPA emits relative URLs (e.g. /documents/...)
# nginx proxies those API roots to the backend container.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ── Stage 2: runtime — nginx alpine ──────────────────────────
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
