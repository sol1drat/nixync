#!/usr/bin/env bash
# Run the Nixync agent on a managed NixOS machine: the background daemon and the
# desktop app, together.
#
#   ./run-agent.sh --server http://192.168.1.10:8000 --machine-id <uuid>
#   ./run-agent.sh --server http://192.168.1.10:8000 --machine-id <uuid> --dry-run
#
# Register the machine in the host app first; it shows the agent id after "Add device".
#
# The daemon writes /etc/nixos/nixync.nix and runs nixos-rebuild, so it needs root —
# this script asks for it with sudo for that process only. The desktop app runs as
# you, because it must reach your display and has no business having root.
#
# Run inside `nix develop` so Qt's native libraries are on the path.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
# Overridable so the script can be exercised without touching the real /etc —
# the daemon and the desktop app both read whatever this points at.
CONFIG="${NIXYNC_AGENT_CONFIG:-/etc/nixync/agent.toml}"
PYTHONPATH="$ROOT/src/back/helpers:$ROOT/src/back/client:$ROOT/src/shared${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

SERVER=""
MACHINE_ID=""
DRY_RUN=""
NO_GUI=""

while [ $# -gt 0 ]; do
    case "$1" in
        --server)     SERVER="$2"; shift 2 ;;
        --machine-id) MACHINE_ID="$2"; shift 2 ;;
        --dry-run)    DRY_RUN="--dry-run"; shift ;;
        --no-gui)     NO_GUI="yes"; shift ;;
        -h|--help)    sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
        *)            echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }

[ -x "$PY" ] || die "no .venv — run 'nix develop', then: pip install -r requirements.txt"

# Fall back to whatever is already configured, so a machine set up once can just run
# ./run-agent.sh with no arguments.
if [ -z "$SERVER" ] && [ -r "$CONFIG" ]; then
    SERVER=$(sed -n 's/^server_url *= *"\(.*\)"/\1/p' "$CONFIG")
    MACHINE_ID=${MACHINE_ID:-$(sed -n 's/^machine_id *= *"\(.*\)"/\1/p' "$CONFIG")}
fi
[ -n "$SERVER" ] || die "no --server given and none in $CONFIG"
[ -n "$MACHINE_ID" ] || die "no --machine-id given and none in $CONFIG. The host app shows it after 'Add device'."

if [ -z "$DRY_RUN" ] && [ ! -d /etc/nixos ]; then
    die "/etc/nixos does not exist — this is meant for a NixOS machine. Try --dry-run."
fi

echo "Nixync agent"
echo "  server      $SERVER"
echo "  machine     $MACHINE_ID"
if [ -n "$DRY_RUN" ]; then
    echo "  mode        DRY RUN — renders and logs, writes nothing, never rebuilds"
else
    echo "  mode        LIVE — writes /etc/nixos/nixync.nix and runs nixos-rebuild switch"
    echo "              Your configuration.nix gains one import line; nothing else of"
    echo "              yours is modified."
fi
echo

# Write the shared config so the desktop app knows which machine it is running on,
# and so a later run needs no arguments.
sudo install -d -m 755 "$(dirname "$CONFIG")"
printf 'server_url = "%s"\nmachine_id = "%s"\n' "$SERVER" "$MACHINE_ID" \
    | sudo tee "$CONFIG" >/dev/null
echo "Wrote $CONFIG"

DAEMON_PID=""
cleanup() {
    if [ -n "$DAEMON_PID" ] && kill -0 "$DAEMON_PID" 2>/dev/null; then
        echo
        echo "Stopping the daemon…"
        # It runs under sudo, so the signal has to go the same way.
        sudo kill -TERM "$DAEMON_PID" 2>/dev/null || true
        wait "$DAEMON_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

echo "Starting the daemon (as root)…"
sudo --preserve-env=PYTHONPATH "$PY" -m nixync_agent.daemon \
    --server "$SERVER" --machine-id "$MACHINE_ID" $DRY_RUN &
DAEMON_PID=$!

sleep 2
kill -0 "$DAEMON_PID" 2>/dev/null || die "the daemon exited immediately — see the output above"

if [ -n "$NO_GUI" ]; then
    echo "Daemon running. Ctrl-C to stop."
    wait "$DAEMON_PID"
    exit $?
fi

echo "Starting the desktop app (as $USER)…"
echo
# Foreground: closing the window stops everything, which is what someone running
# this by hand expects.
"$PY" -m nixync_agent.gui --config "$CONFIG"
