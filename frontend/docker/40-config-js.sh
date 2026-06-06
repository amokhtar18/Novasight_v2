#!/bin/sh
# Generate the runtime config.js from the environment at container start.
# nginx's official image runs every executable in /docker-entrypoint.d/ before
# launching nginx, so this writes config.js before the first request.
#
# Only apiBaseUrl is needed — authentication is handled by the in-app login.
set -eu

API_BASE_URL="${API_BASE_URL:-/api/v1}"

cat > /usr/share/nginx/html/config.js <<EOF
window.__APP_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };
EOF

echo "config.js written: apiBaseUrl=${API_BASE_URL}"
