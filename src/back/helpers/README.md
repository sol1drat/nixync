# Nixync agent

What runs on a managed NixOS machine. Two parts, one package:

- **The daemon** holds a WebSocket to the Nixync server, reports CPU/RAM/disk, and
  turns each configuration push into real NixOS configuration — render, write,
  rebuild, report back.
- **The desktop app** is for whoever is sitting at the machine: ask for an
  application, see what was decided, and see how the machine is doing.

Register the machine in the host app first — it shows the **agent id** in the status
bar after *Add device*, and on the device's settings page.

## Trying it

```sh
nix develop                     # Qt's native libraries come from the flake
pip install -r requirements.txt # first time only
./run-agent.sh --server http://<host-ip>:8000 --machine-id <agent-id> --dry-run
```

`--dry-run` renders and logs but writes nothing and never rebuilds, so it is safe
anywhere. Drop it to apply for real. `--no-gui` runs the daemon alone.

## Installing it permanently

```sh
sudo ./install-agent.sh --server http://<host-ip>:8000 --machine-id <agent-id>
```

The daemon becomes a systemd **system** service: it starts at boot, restarts if it
dies, and — being root-owned — only root can stop it, which is the point on a
machine someone else administers.

On NixOS the service is **declared** as `/etc/nixos/nixync-agent.nix`, imported from
`configuration.nix`, and realised by `nixos-rebuild switch`. A unit file cannot be
dropped into `/etc/systemd/system` there: it is a symlink into the read-only Nix
store. On other distributions the script writes a plain unit instead.

```sh
sudo systemctl stop nixync-agent     # needs root
journalctl -u nixync-agent -f        # what it is doing
```

It also adds **Nixync** to the applications menu in KDE, XFCE and anything else
reading XDG desktop entries, and starts it at login.

`--dry-run` prints the unit and the desktop entry without installing either, and
does not need root. `sudo ./install-agent.sh --uninstall` removes both; it leaves
`/etc/nixos` alone and tells you what to remove to detach the machine fully.

## What it does to the machine

Nixync owns exactly one file, `/etc/nixos/nixync.nix`, and adds a single import line
to your `configuration.nix`:

```nix
imports = [ ./hardware-configuration.nix ./nixync.nix ];
```

Everything else is yours and is never rewritten. Remove the import and the file and
the machine is exactly as it was.

Settings are emitted with `lib.mkDefault`, so anything your own configuration
already defines wins. NixOS refuses two definitions of a scalar option, so without
this a `nixync.nix` setting `networking.hostName` would break the rebuild on any
machine that sets it too. The trade-off: Nixync cannot override a setting the
machine defines for itself.

A rebuild that fails restores the previous `nixync.nix`, the previous
`configuration.nix` and the previous recorded state, then reports the tail of the
build log — which is what the administrator sees next to the machine. A failed
deployment cannot leave the machine unable to rebuild, including at boot.

## Why root, and only for the daemon

Writing `/etc/nixos` and running `nixos-rebuild` need it. The desktop app does not,
and never gets it.

## Development

```sh
./run-demo.sh tests
```

No test writes outside a temp directory, and an autouse fixture fails any test that
reaches a real `nixos-rebuild` — the rebuild command is injected, not patched.

See `SPEC.md` for the design and `CAPABILITY-MAP.md` for how the modules fit together.
