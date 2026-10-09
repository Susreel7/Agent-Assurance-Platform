ARG NODE_VERSION=22

# ------------------------------------------------------------------ dev
#
# Vite's dev server, for the development stack. This target exists because the
# `runtime` target below bakes the built bundle into the image, and a baked bundle
# in a *development* stack is a trap rather than a trade-off: the console then shows
# whatever was compiled the last time somebody remembered to rebuild the image, while
# every other service in the compose file reloads from a source mount. The two drifted
# for a whole session — the api served code written minutes ago and the console served
# a bundle from hours earlier, with no error anywhere to say so. The only visible
# symptom was that newly added screens "did not work", because their routes and nav
# entries genuinely did not exist in the bundle being served.
#
# So: the development stack mounts source and runs Vite. `runtime` stays exactly as it
# was for real deployments, where an immutable bundle is the right answer.
FROM node:${NODE_VERSION}-alpine AS dev

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the port publishes out of the container at all; Vite defaults
# to localhost, which from the host looks like the server never started.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# ------------------------------------------------------------------ builder
FROM node:${NODE_VERSION}-alpine AS builder

WORKDIR /build

COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

COPY . .

# Baked at build time, so a BYOC customer's bundle points at their own hostname.
ARG VITE_API_BASE=/
ENV VITE_API_BASE=${VITE_API_BASE}

# `live` talks to the API through the nginx /v1 proxy; `mock` serves the fixture set from
# src/mocks and never opens a socket. The container default is `live`, because a running
# stack that quietly shows fixtures is worse than one that shows an error: the fixtures
# look like a working product, so nobody investigates. The mock path stays for frontend
# work without a backend, which is what `npm run dev` gives you.
ARG VITE_API_MODE=live
ENV VITE_API_MODE=${VITE_API_MODE}

ARG VITE_MCP_ADAPTER_BASE=
ENV VITE_MCP_ADAPTER_BASE=${VITE_MCP_ADAPTER_BASE}

RUN npm run build

# ------------------------------------------------------------------ runtime
FROM nginx:alpine AS runtime

RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=builder /build/dist /usr/share/nginx/html

# nginx:alpine ships an unprivileged user; use it rather than running as root.
#
# That user cannot write the default /var/run/nginx.pid, so the path has to move. `pid`
# is valid only in nginx's main context, which rules out the conf.d snippet, and passing
# it via `-g` collides with the directive already in nginx.conf ("pid directive is
# duplicate"). Rewriting the line in place is what actually works. `user` goes too — it
# is ignored without root and only emits a warning on every boot.
RUN sed -i 's|^pid .*|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf \
    && sed -i '/^user /d' /etc/nginx/nginx.conf \
    && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx

USER nginx

EXPOSE 80

# 127.0.0.1 rather than localhost, so the check does not depend on how the container's
# resolver happens to order A and AAAA records.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
