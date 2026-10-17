#!/usr/bin/env bash
# Start a piece of the Nixync demo.
#
#   ./run-demo.sh server          the fleet server, reachable from other machines
#   ./run-demo.sh gui             the desktop app
#   ./run-demo.sh agent <id>      a machine agent (prints instead of installing)
#   ./run-demo.sh tests           the whole test suite
#
# On NixOS the pip-installed PySide6 cannot find its native libraries, so this
# resolves them from the store and exports LD_LIBRARY_PATH before launching Qt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
SERVER_URL="${NIXYNC_SERVER_URL:-http://127.0.0.1:8000}"

[ -x "$PY" ] || { echo "No .venv — run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }

qt_libs() {
    # Each Qt import failure names one missing library; find a 64-bit copy of it in
    # the store and try again. Skip directories holding their own libc, which would
    # shadow the system one and break every other binary.
    local libs="" missing found d
    for _ in $(seq 1 15); do
        missing=$(LD_LIBRARY_PATH="$libs" QT_QPA_PLATFORM=offscreen "$PY" -c \
            'from PySide6.QtWidgets import QApplication' 2>&1 \
            | grep -oP '^ImportError: \K[^:]+\.so[^:]*' | head -1) || true
        [ -z "$missing" ] && break
        found=""
        for d in $(find /nix/store -maxdepth 2 -type d -name lib 2>/dev/null); do
            if [ -e "$d/$missing" ] && [ ! -e "$d/libc.so.6" ]; then
                file -L "$d/$missing" 2>/dev/null | grep -q 'ELF 64-bit' && { found="$d"; break; }
            fi
        done
        [ -z "$found" ] && { echo "Could not find $missing in /nix/store" >&2; break; }
        libs="${libs:+$libs:}$found"
    done
    echo "$libs"
}

with_qt() {
    local cached="$ROOT/.qt-libs"
    [ -s "$cached" ] || { echo "Resolving Qt libraries (first run only)…" >&2; qt_libs > "$cached"; }
    export LD_LIBRARY_PATH="$(cat "$cached")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
}

case "${1:-}" in
server)
    cd "$ROOT/src/back/server"
    echo "Serving on 0.0.0.0:8000 — reachable from other machines on your network."
    echo "Sign in with admin / password. Interactive API docs: http://127.0.0.1:8000/docs"
    exec env NIXYNC_DB="${NIXYNC_DB:-$ROOT/nixync.db}" \
        "$PY" -m uvicorn server:app --host 0.0.0.0 --port 8000
    ;;
gui)
    with_qt
    cd "$ROOT/src/front"
    echo "Connecting to $SERVER_URL — sign in with admin / password."
    exec env NIXYNC_SERVER_URL="$SERVER_URL" "$PY" -m nixync_front
    ;;
agent)
    [ -n "${2:-}" ] || { echo "Usage: $0 agent <machine-id>   (the app shows it after Add device)" >&2; exit 1; }
    exec "$PY" "$ROOT/src/back/client/example_agent.py" \
        --server "$SERVER_URL" --machine-id "$2" --telemetry-interval 10
    ;;
tests)
    with_qt
    cd "$ROOT"
    exec env QT_QPA_PLATFORM=offscreen "$PY" -m pytest src/back/server src/back/client src/front "${@:2}"
    ;;
*)
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    exit 1
    ;;
esac
