#!/usr/bin/env bash
# Install the Nixync agent on a managed NixOS machine.
#
#   sudo ./install-agent.sh --server http://192.168.1.10:8000 --machine-id <uuid>
#   sudo ./install-agent.sh --uninstall
#
# Installs two things:
#   * nixync-agent.service — the daemon, as a systemd system service. It starts at
#     boot and restarts if it dies. Being a system service, only root can stop it,
#     which is the point on a machine someone else administers.
#   * A desktop entry — so "Nixync" appears in the KDE/XFCE applications menu, and
#     starts automatically when the user logs in.
#
# Register the machine in the host app first; it shows the agent id after "Add device".
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$ROOT/.venv/bin/python"
UNIT_NAME="nixync-agent.service"
UNIT="/etc/systemd/system/$UNIT_NAME"
CONFIG_DIR="/etc/nixync"
CONFIG="$CONFIG_DIR/agent.toml"
DESKTOP_NAME="nixync-agent.desktop"

SERVER=""; MACHINE_ID=""; UNINSTALL=""; DRY_RUN=""
while [ $# -gt 0 ]; do
    case "$1" in
        --server)     SERVER="$2"; shift 2 ;;
        --machine-id) MACHINE_ID="$2"; shift 2 ;;
        --uninstall)  UNINSTALL="yes"; shift ;;
        --dry-run)    DRY_RUN="yes"; shift ;;
        -h|--help)    sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
        *)            echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

die() { echo "error: $*" >&2; exit 1; }

# Root is needed to install, but not to look: --dry-run has to work without it, or
# nobody can see what this would put on their machine before it does.
if [ -z "$DRY_RUN" ]; then
    [ "$(id -u)" = "0" ] || die "run this with sudo — it installs a system service."
fi

# The desktop entry belongs to the person who will use the machine, not to root.
TARGET_USER="${SUDO_USER:-$(id -un)}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[ -n "$TARGET_HOME" ] || die "could not find a home directory for $TARGET_USER"

if [ -n "$UNINSTALL" ]; then
    echo "Removing the Nixync agent…"
    systemctl disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT"
    systemctl daemon-reload
    rm -f "$TARGET_HOME/.local/share/applications/$DESKTOP_NAME"
    rm -f "$TARGET_HOME/.config/autostart/$DESKTOP_NAME"
    echo "Removed the service and the desktop entries."
    echo "Left alone: $CONFIG_DIR, and anything already written to /etc/nixos."
    echo "To detach this machine completely, also remove ./nixync.nix from"
    echo "/etc/nixos/configuration.nix and delete /etc/nixos/nixync.nix."
    exit 0
fi

[ -x "$PY" ] || die "no .venv at $PY — run 'nix develop' and install requirements.txt first."

# Fall back to an existing config so a reinstall needs no arguments.
if [ -z "$SERVER" ] && [ -r "$CONFIG" ]; then
    SERVER=$(sed -n 's/^server_url *= *"\(.*\)"/\1/p' "$CONFIG")
    MACHINE_ID=${MACHINE_ID:-$(sed -n 's/^machine_id *= *"\(.*\)"/\1/p' "$CONFIG")}
fi
[ -n "$SERVER" ] || die "no --server given and none in $CONFIG"
[ -n "$MACHINE_ID" ] || die "no --machine-id given and none in $CONFIG"

emit_unit() {
cat <<UNIT_EOF
[Unit]
Description=Nixync agent — keeps this machine in step with the Nixync server
Documentation=file://$ROOT/src/back/helpers/README.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Root: it writes /etc/nixos/nixync.nix and runs nixos-rebuild.
User=root
Environment=PYTHONPATH=$ROOT/src/back/helpers:$ROOT/src/back/client:$ROOT/src/shared
ExecStart=$PY -m nixync_agent.daemon --config $CONFIG
Restart=always
RestartSec=10
# A rebuild can take a long while; do not kill it partway.
TimeoutStopSec=300

[Install]
WantedBy=multi-user.target
UNIT_EOF
}

emit_desktop() {
cat <<DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Nixync
GenericName=Managed software
Comment=Request software and see how this machine is doing
Exec=env PYTHONPATH=$ROOT/src/back/helpers:$ROOT/src/back/client:$ROOT/src/shared $PY -m nixync_agent.gui
Icon=$ROOT/src/shared/nixync_ui/icons/app-icon.png
Terminal=false
Categories=System;Utility;
Keywords=nixos;packages;software;nixync;
StartupNotify=true
DESKTOP_EOF
}

if [ -n "$DRY_RUN" ]; then
    echo "=== $UNIT ==="; emit_unit
    echo; echo "=== $DESKTOP_NAME ==="; emit_desktop
    exit 0
fi

echo "Installing the Nixync agent"
echo "  server   $SERVER"
echo "  machine  $MACHINE_ID"
echo "  for      $TARGET_USER"
echo

install -d -m 755 "$CONFIG_DIR"
printf 'server_url = "%s"\nmachine_id = "%s"\n' "$SERVER" "$MACHINE_ID" > "$CONFIG"
chmod 644 "$CONFIG"
echo "Wrote $CONFIG"

emit_unit > "$UNIT"
chmod 644 "$UNIT"
systemctl daemon-reload
systemctl enable --now "$UNIT_NAME"
echo "Installed and started $UNIT_NAME"

for dir in "$TARGET_HOME/.local/share/applications" "$TARGET_HOME/.config/autostart"; do
    install -d -o "$TARGET_USER" -g "$(id -gn "$TARGET_USER")" -m 755 "$dir"
    emit_desktop > "$dir/$DESKTOP_NAME"
    chown "$TARGET_USER:$(id -gn "$TARGET_USER")" "$dir/$DESKTOP_NAME"
    chmod 644 "$dir/$DESKTOP_NAME"
done
echo "Added “Nixync” to $TARGET_USER's applications menu, and to login autostart."

# KDE and XFCE cache the menu; without this the entry can take a re-login to appear.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$TARGET_HOME/.local/share/applications" 2>/dev/null || true
fi

echo
echo "Done. The daemon runs as root, so stopping it needs root:"
echo "    sudo systemctl stop $UNIT_NAME"
echo "Follow what it is doing with:"
echo "    journalctl -u $UNIT_NAME -f"
echo "Remove everything with:"
echo "    sudo $ROOT/install-agent.sh --uninstall"
