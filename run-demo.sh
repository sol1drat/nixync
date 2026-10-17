#!/usr/bin/env bash
# Start a piece of the Nixync demo.
#
#   ./run-demo.sh server          the fleet server, reachable from other machines
#   ./run-demo.sh machines        list the rows of the machines table
#   ./run-demo.sh gui             the desktop app
#   ./run-demo.sh agent <id>      a machine agent (prints instead of installing)
#   ./run-demo.sh tests           the whole test suite
#
# Run inside `nix develop` so native libraries are provided by the flake.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
SERVER_URL="${NIXYNC_SERVER_URL:-http://127.0.0.1:8000}"

if [ ! -x "$PY" ]; then
    echo "No .venv — enter 'nix develop' to create it, then install requirements.txt." >&2
    exit 1
fi

case "${1:-}" in
server)
    cd "$ROOT/src/back/server"
    echo "Serving on 0.0.0.0:8000 — reachable from other machines on your network."
    echo "Sign in with admin / password. Interactive API docs: http://127.0.0.1:8000/docs"
    exec env NIXYNC_DB="${NIXYNC_DB:-$ROOT/nixync.db}" \
        "$PY" -m uvicorn server:app --host 0.0.0.0 --port 8000
    ;;

machines)
    exec env NIXYNC_DB="${NIXYNC_DB:-$ROOT/nixync.db}" \
        "$PY" "$ROOT/src/back/server/scripts/list_machines.py" "${@:2}"
    ;;

gui)
    cd "$ROOT/src/front"
    echo "Connecting to $SERVER_URL — sign in with admin / password."
    exec env NIXYNC_SERVER_URL="$SERVER_URL" "$PY" -m nixync_front
    ;;

agent)
    [ -n "${2:-}" ] || {
        echo "Usage: $0 agent <machine-id> (the app shows it after Add device)" >&2
        exit 1
    }
    exec "$PY" "$ROOT/src/back/client/example_agent.py" \
        --server "$SERVER_URL" --machine-id "$2" --telemetry-interval 10
    ;;

tests)
    cd "$ROOT"
    exec env QT_QPA_PLATFORM=offscreen \
        "$PY" -m pytest src/back/server src/back/client src/back/helpers src/front src/shared "${@:2}"
    ;;

*)
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 1
    ;;
esac
