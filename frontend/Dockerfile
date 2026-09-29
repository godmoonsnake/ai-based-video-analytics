# Multi-stage production build for the DARSON operator dashboard.
#
# Stage 1 (build): compile the React + TS app with Vite. VITE_API_BASE is left
# empty so the app issues SAME-ORIGIN relative requests (e.g. /api/v1/...), which
# the reverse proxy routes to the backend. No backend hostname or secret is baked
# into the JS bundle.
#
# Stage 2 (serve): a lightweight nginx serving only the static build output. This
# container does NOT reverse-proxy the API — the dedicated `proxy` service does.
FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Same-origin: empty API base => relative fetch() paths resolved at the proxy.
ENV VITE_API_BASE=""
RUN npm run build

FROM nginx:1.27-alpine AS serve
# SPA config: serve the built assets and fall back to index.html for client routes.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
