# syntax=docker/dockerfile:1
FROM nginx:1.27-alpine@sha256:4ff102c5d78d254a6f0da062b3cf39eaf07f01eec0927fd21e219d0af8bc0591 AS serve

COPY site/ /usr/share/nginx/html/

# The server runs as nginx, which owns what it serves.
RUN <<EOF
set -eu
chown -R nginx:nginx /usr/share/nginx/html
EOF

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s \
  CMD wget -qO- http://localhost:8080/ || exit 1
