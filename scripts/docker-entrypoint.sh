#!/bin/sh
# Entrypoint of the Mimi container image (see Dockerfile).
#   serve [args]        run Mimi Core (default)
#   content <cmd> ...   the content manager: list, status, regions, add, remove, verify
#   doctor              diagnostics
#   anything else       run it as a command
set -eu
mkdir -p "$MIMI_CONTENT" "$MIMI_DATA" "$MIMI_LOGS" 2>/dev/null || {
    echo "mimi: can't write to $MIMI_CONTENT. If /data is a bind mount, make it writable by uid $(id -u)," >&2
    echo "      e.g. sudo chown -R $(id -u):$(id -g) <host folder>, or set user: in docker-compose.yml." >&2
    exit 1
}
cmd=${1:-serve}
[ $# -gt 0 ] && shift
case "$cmd" in
    serve) exec python -m mimi serve "$@" ;;
    content) exec python /opt/mimi/scripts/content.py "$@" ;;
    doctor) exec python -m mimi doctor "$@" ;;
    *) exec "$cmd" "$@" ;;
esac
