#!/bin/sh
set -e

# A mounted volume can be created as root. Fix ownership once, before dropping
# privileges, so SQLite can write. Postgres deployments simply ignore this.
if [ "$(id -u)" = "0" ]; then
  mkdir -p /data 2>/dev/null || true
  chown -R appuser:appuser /data 2>/dev/null || true
  exec gosu appuser "$@"
fi

exec "$@"
