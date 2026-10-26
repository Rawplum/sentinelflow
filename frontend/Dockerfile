# Build the console, then serve the static bundle from an unprivileged nginx.
#
# Two stages so node and the dev dependencies never reach the runtime image.

FROM node:22-alpine AS build

WORKDIR /app

# Lockfile first: the dependency layer is cached until package.json changes.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
# The bundle is served from the same origin as the API (see nginx.conf), so the
# default relative base URL '/api/v1' is what we want.
RUN npm run build


FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime

# Runs as uid 101, listens on 8080; no root, no privileged port.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
