"""Validate a device's editable NixOS settings, and preview them as Nix.

Validation and diffing live here because they are form concerns. The rendering
itself does not: the agent writes the same Nix to real machines, so there is one
renderer in `nixync_client.nix` and this module just adapts the UI's dataclass to it.
A second implementation would drift, and the preview would stop matching the file
that actually lands on the device.
"""

import ipaddress
import re
from dataclasses import fields

from nixync_front.sample_data import SystemSettings

# networking.hostName: letters, digits and dashes, no dots, 1-63 chars, no dash at either end.
HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
ROOT_LOGIN = ["no", "prohibit-password", "yes"]
# NixOS user names: start with a lowercase letter or _, then lowercase letters, digits, - or _.
USERNAME = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
RESERVED_USERS = {"root", "nobody", "nixbld", "messagebus", "sshd", "systemd-network", "nixync"}


def username_error(value: str, taken: list[str]) -> str:
    if not value:
        return "Enter a username."
    if not USERNAME.match(value):
        return "Use lowercase letters, digits, - or _, starting with a letter (up to 32 characters)."
    if value in RESERVED_USERS:
        return f"“{value}” is reserved by the system."
    if value in taken:
        return f"There's already a user called “{value}”."
    return ""


def hostname_error(value: str) -> str:
    if not value:
        return "Hostname can't be empty."
    if "." in value:
        return "No dots: use the short name (e.g. lab-05), not a full domain."
    if not HOSTNAME.match(value):
        return "Use letters, digits and dashes (not at the start or end), up to 63 characters."
    return ""


def parse_nameservers(text: str) -> tuple[list[str], str]:
    servers = [s for s in re.split(r"[,\s]+", text.strip()) if s]
    for server in servers:
        try:
            ipaddress.ip_address(server)
        except ValueError:
            return servers, f"“{server}” isn't an IP address."
    return servers, ""


def parse_ports(text: str) -> tuple[list[int], str]:
    ports = []
    for part in [p for p in re.split(r"[,\s]+", text.strip()) if p]:
        if not part.isdigit() or not 1 <= int(part) <= 65535:
            return ports, f"“{part}” isn't a port (1–65535)."
        if int(part) not in ports:
            ports.append(int(part))
    return ports, ""


def changed_fields(old: SystemSettings, new: SystemSettings) -> list[str]:
    labels = {"hostname": "hostname", "timezone": "time zone", "nameservers": "DNS servers",
              "firewall": "firewall", "open_tcp_ports": "open ports", "ssh": "SSH",
              "ssh_password_login": "SSH password login", "ssh_root_login": "SSH root login",
              "bluetooth": "Bluetooth", "sound": "sound", "docker": "Docker", "allow_unfree": "unfree packages",
              "users": "users"}
    return [labels[f.name] for f in fields(SystemSettings) if getattr(old, f.name) != getattr(new, f.name)]


def render(s: SystemSettings) -> str:
    """The Nix that Nixync will put on the device for these settings.

    Shows exactly what the agent would write, because it is the same renderer.
    """
    from nixync_client.nix import render as render_config
    from nixync_front.api import _settings_to_server
    from nixync_client.protocol import MachineConfig

    return render_config(MachineConfig(settings=_settings_to_server(s)))
