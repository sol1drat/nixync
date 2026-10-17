"""Thin client for the Nixync FastAPI server.

Only GET /status exists on the server today. The other methods are the
calls the UI expects; they return sample data until the server grows them.
"""

from datetime import datetime

import requests

from nixync_front import nixos_search, sample_data
from nixync_front.config import Config


class ApiError(Exception):
    pass


class NixyncClient:
    def __init__(self, config: Config):
        self.base_url = config.server_url
        self.timeout = config.request_timeout
        self.search_index = config.nixos_search_index
        self.session = requests.Session()

    def _get(self, path: str):
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ApiError(str(e)) from e

    # TODO: replace with POST /login once the server has authentication; it should
    # check the credentials and return a session token for later requests.
    def login(self, username: str, password: str) -> dict:
        if not username or not password:
            raise ApiError("Enter your username and password.")
        return {"username": username}

    def get_status(self) -> dict:
        return self._get("/status")

    # TODO: replace with GET /machines once the server has it.
    def list_machines(self) -> list[sample_data.Machine]:
        return list(sample_data.MACHINES)

    # TODO: replace with GET /machines/{name} once the server has it.
    def get_machine(self, name: str) -> sample_data.Machine:
        return next(m for m in sample_data.MACHINES if m.name == name)

    # TODO: replace with a POST to the server, which then builds each device.
    def add_apps(self, devices: list[str], apps: list[str]) -> dict[str, list[str]]:
        """Add apps to several devices. Returns what was actually added per device,
        skipping apps a device already has from its preset or its own list."""
        added = {}
        for name in devices:
            machine = self.get_machine(name)
            preset = self.get_preset(machine.preset)
            have = set(machine.extra_apps) | set(preset.extra_apps if preset else [])
            new = [a for a in apps if a not in have]
            machine.extra_apps.extend(new)
            added[name] = new
        return added

    # TODO: replace with GET /presets once the server has it.
    def list_presets(self) -> list[sample_data.Preset]:
        return list(sample_data.PRESETS)

    def get_preset(self, name: str) -> sample_data.Preset | None:
        return next((p for p in self.list_presets() if p.name == name), None)

    def search_apps(self, query: str) -> list[nixos_search.Package]:
        """Search nixpkgs on search.nixos.org. Blocking; call it off the UI thread."""
        return nixos_search.search(query, self.search_index)

    # TODO: replace with GET /requests once the server has it.
    def list_requests(self) -> list[sample_data.AppRequest]:
        return sorted(sample_data.REQUESTS, key=lambda r: r.when, reverse=True)

    def pending_requests(self, machine: str | None = None) -> list[sample_data.AppRequest]:
        return [r for r in self.list_requests()
                if r.status is sample_data.RequestStatus.PENDING and machine in (None, r.machine)]

    # TODO: replace with POST /requests/{id}/approve once the server has it.
    # Approving adds the app to the machine; the server should then start a build.
    def approve_request(self, request_id: int) -> sample_data.AppRequest:
        request = self._request(request_id)
        request.status = sample_data.RequestStatus.APPROVED
        machine = self.get_machine(request.machine)
        if request.app not in machine.extra_apps:
            machine.extra_apps.append(request.app)
        return request

    # TODO: replace with POST /requests/{id}/decline once the server has it.
    def decline_request(self, request_id: int) -> sample_data.AppRequest:
        request = self._request(request_id)
        request.status = sample_data.RequestStatus.DECLINED
        return request

    # TODO: replace with POST /requests once the server has it (sent from the device's client app).
    def create_request(self, machine: str, app: str, requested_by: str, reason: str) -> sample_data.AppRequest:
        request = sample_data.AppRequest(
            id=max((r.id for r in sample_data.REQUESTS), default=0) + 1,
            machine=machine, app=app, requested_by=requested_by,
            when=datetime.now(), reason=reason,
        )
        sample_data.REQUESTS.append(request)
        return request

    def installed_apps(self, machine: str) -> set[str]:
        """Apps the device already has: its preset's apps plus its own."""
        m = self.get_machine(machine)
        preset = self.get_preset(m.preset)
        return set(m.extra_apps) | set(preset.extra_apps if preset else [])

    # TODO: send to the server, which rebuilds the device. For new users it should set the
    # password on the device itself (hashed there); passwords never go into the Nix config.
    def save_settings(self, machine: str, settings: sample_data.SystemSettings, passwords: dict[str, str] | None = None):
        self.get_machine(machine).settings = settings

    def _request(self, request_id: int) -> sample_data.AppRequest:
        return next(r for r in sample_data.REQUESTS if r.id == request_id)

    def describe_app(self, name: str) -> str:
        return next((a.description for a in sample_data.APP_CATALOG if a.name == name), "")

    # TODO: replace with GET /updates/current once the server has it.
    def current_update(self) -> sample_data.Update:
        return sample_data.CURRENT_UPDATE
