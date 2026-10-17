"""The desktop app's view of the Nixync server.

Machines, apps and device settings are real: this delegates to `nixync_client`, the
library that owns the wire protocol, rather than building requests by hand. Presets,
groups, app requests and the updates page still come from `sample_data` — the server
has no data model for them yet, and each is marked below.

The UI reads `sample_data.Machine`, so the server's richer record is mapped onto that
shape instead of changing a view model that a dozen files depend on. Fields the server
has no concept of keep their sample defaults rather than being invented.

Every call here is blocking; the pages already run them on worker threads.
"""

from dataclasses import asdict
from datetime import datetime

from nixync_client import AdminClient, NixyncApiError
from nixync_client import Machine as ServerMachine

from nixync_front import nixos_search, sample_data
from nixync_front.config import Config


class ApiError(Exception):
    pass


def _health_of(machine: ServerMachine) -> sample_data.Health:
    """Collapse the server's separate liveness and deployment state into one badge.

    A failed deployment outranks being unreachable: a machine that broke and then went
    away is a problem to show, not an absence.
    """
    if machine.last_apply_status == "failed":
        return sample_data.Health.PROBLEM
    if not machine.online:
        return sample_data.Health.UNREACHABLE
    return sample_data.Health.OK


def _ram_percent(machine: ServerMachine) -> float | None:
    if machine.ram_used_mb is None or not machine.ram_total_mb:
        return None
    return 100 * machine.ram_used_mb / machine.ram_total_mb


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _settings_from(stored: dict, hostname: str) -> sample_data.SystemSettings:
    """Rebuild SystemSettings from the free-form dict the server stores.

    Unknown keys are dropped rather than raising: a newer client may have written
    settings this build does not know about, and losing one toggle beats a crash.
    """
    known = sample_data.SystemSettings.__dataclass_fields__
    values = {k: v for k, v in (stored or {}).items() if k in known and k != "users"}
    values.setdefault("hostname", hostname)
    settings = sample_data.SystemSettings(**values)
    settings.users = [
        sample_data.LocalUser(**{k: v for k, v in user.items()
                                 if k in sample_data.LocalUser.__dataclass_fields__})
        for user in (stored or {}).get("users", [])
    ]
    return settings


def _to_view_model(
    machine: ServerMachine,
    *,
    preset: str = "",
    group: str = "",
    address: str = "",
) -> sample_data.Machine:
    """Map the server's machine onto the record the UI renders."""
    return sample_data.Machine(
        name=machine.name,
        # Preset/group/address have no server model yet; the add-device dialog can
        # still supply them for this session so the fleet view is not blank.
        preset=preset,
        group=group,
        address=address,
        health=_health_of(machine),
        note=machine.last_apply_message or "",
        cpu_percent=machine.cpu_percent,
        ram_percent=_ram_percent(machine),
        last_seen=_parse_time(machine.metrics_reported_at),
        disk_used_gb=machine.disk_used_gb,
        disk_total_gb=machine.disk_total_gb,
        settings=_settings_from(machine.config.settings, machine.name),
        extra_apps=list(machine.config.packages),
    )


class NixyncClient:
    def __init__(self, config: Config):
        self.base_url = config.server_url
        self.timeout = config.request_timeout
        self.search_index = config.nixos_search_index
        self._admin = AdminClient(config.server_url, timeout=config.request_timeout)
        # The UI names machines; the server identifies them by id. Filled on every
        # list_machines() so later calls can translate without a second round trip.
        self._ids: dict[str, str] = {}
        # Presentation-only fields collected by the add-device dialog. Lost on
        # restart — the server cannot store them yet (see src/front/SPEC.md).
        self._labels: dict[str, dict[str, str]] = {}

    # -- plumbing ----------------------------------------------------------

    def _machine_id(self, name: str) -> str:
        if name in self._ids:
            return self._ids[name]
        try:
            found = self._admin.find_machine_by_name(name)
        except NixyncApiError as e:
            raise ApiError(str(e)) from e
        if found is None:
            raise ApiError(f"No machine called “{name}” on the server.")
        self._ids[name] = found.id
        return found.id

    # -- sign-in -----------------------------------------------------------

    def login(self, username: str, password: str) -> dict:
        if not username or not password:
            raise ApiError("Enter your username and password.")
        try:
            return self._admin.login(username, password)
        except NixyncApiError as e:
            if e.status_code == 401:
                raise ApiError("Incorrect username or password.") from e
            raise ApiError(f"Can't reach the server: {e}") from e

    def get_status(self) -> dict:
        try:
            return self._admin.get_status()
        except NixyncApiError as e:
            raise ApiError(str(e)) from e

    # -- machines ----------------------------------------------------------

    def list_machines(self) -> list[sample_data.Machine]:
        try:
            machines = self._admin.list_machines()
        except NixyncApiError as e:
            raise ApiError(str(e)) from e
        # Cache only unambiguous names. Duplicates stay out so a later lookup raises
        # instead of silently picking one — the fleet view can still list them all.
        counts: dict[str, int] = {}
        for machine in machines:
            counts[machine.name] = counts.get(machine.name, 0) + 1
        self._ids = {m.name: m.id for m in machines if counts[m.name] == 1}
        return [self._view_model(m) for m in machines]

    def get_machine(self, name: str) -> sample_data.Machine:
        try:
            return self._view_model(self._admin.get_machine(self._machine_id(name)))
        except NixyncApiError as e:
            raise ApiError(str(e)) from e

    def add_machine(
        self,
        name: str,
        *,
        preset: str = "",
        group: str = "",
        address: str = "",
    ) -> sample_data.Machine:
        """Register a machine. The returned id is what its agent connects with.

        `preset`, `group` and `address` are kept for this session only — the server
        has no place for them yet, but the add dialog collects them and the UI
        should still show what the operator chose.
        """
        try:
            machine = self._admin.register_machine(name)
        except NixyncApiError as e:
            raise ApiError(str(e)) from e
        self._ids[machine.name] = machine.id
        if preset or group or address:
            self._labels[machine.name] = {
                "preset": preset,
                "group": group,
                "address": address,
            }
        return self._view_model(machine)

    def remove_machine(self, name: str) -> None:
        try:
            self._admin.remove_machine(self._machine_id(name))
        except NixyncApiError as e:
            raise ApiError(str(e)) from e
        self._ids.pop(name, None)
        self._labels.pop(name, None)

    def _view_model(self, machine: ServerMachine) -> sample_data.Machine:
        labels = self._labels.get(machine.name, {})
        return _to_view_model(
            machine,
            preset=labels.get("preset", ""),
            group=labels.get("group", ""),
            address=labels.get("address", ""),
        )

    def machine_id(self, name: str) -> str:
        """The id to hand to that machine's agent."""
        return self._machine_id(name)

    # -- apps --------------------------------------------------------------

    def add_apps(self, devices: list[str], apps: list[str]) -> dict[str, list[str]]:
        """Deploy apps to several devices.

        Returns what was actually new per device, so the UI can report "nothing to do"
        honestly instead of claiming it installed something already present.
        """
        added: dict[str, list[str]] = {}
        for name in devices:
            # Only what the server actually holds counts as installed. A preset is
            # sample data the server never deploys, so treating its apps as present
            # would silently drop the request: the UI would report "already has it"
            # for a package that never reaches the device.
            have = set(self.get_machine(name).extra_apps)
            new = [a for a in apps if a not in have]
            added[name] = new
            if new:
                try:
                    self._admin.add_packages(new, machine_ids=[self._machine_id(name)])
                except NixyncApiError as e:
                    raise ApiError(str(e)) from e
        return added

    def set_apps(self, machine: str, apps: list[str]) -> tuple[list[str], list[str]]:
        """Make a device's extra-app list match `apps`.

        The machine-config page edits the full list, so this adds what was newly chosen
        and removes what was dropped. Returns `(added, removed)`.
        """
        current = set(self.get_machine(machine).extra_apps)
        desired = list(dict.fromkeys(apps))  # preserve order, drop duplicates
        added = [a for a in desired if a not in current]
        removed = sorted(current - set(desired))
        machine_id = self._machine_id(machine)
        try:
            if added:
                self._admin.add_packages(added, machine_ids=[machine_id])
            if removed:
                self._admin.remove_packages(removed, machine_ids=[machine_id])
        except NixyncApiError as e:
            raise ApiError(str(e)) from e
        return added, removed

    def installed_apps(self, machine: str) -> set[str]:
        """Apps the device has: whatever the server holds for it, plus its preset's."""
        m = self.get_machine(machine)
        preset = self.get_preset(m.preset)
        return set(m.extra_apps) | set(preset.extra_apps if preset else [])

    def search_apps(self, query: str) -> list[nixos_search.Package]:
        """Search nixpkgs on search.nixos.org. Blocking; call it off the UI thread."""
        return nixos_search.search(query, self.search_index)

    def describe_app(self, name: str) -> str:
        return next((a.description for a in sample_data.APP_CATALOG if a.name == name), "")

    # -- device settings ---------------------------------------------------

    def save_settings(
        self,
        machine: str,
        settings: sample_data.SystemSettings,
        passwords: dict[str, str] | None = None,
    ):
        """Store a device's system settings and deploy them.

        Passwords are deliberately not sent: they belong on the device, hashed there,
        and must never reach the Nix configuration.
        """
        try:
            self._admin.set_settings(self._machine_id(machine), asdict(settings))
        except NixyncApiError as e:
            raise ApiError(str(e)) from e

    # -- not backed by the server yet --------------------------------------
    # Presets, groups, app requests and the updates page have no server data model.
    # These stay on sample data until they do; see src/front/SPEC.md.

    def list_presets(self) -> list[sample_data.Preset]:
        return list(sample_data.PRESETS)

    def get_preset(self, name: str) -> sample_data.Preset | None:
        return next((p for p in self.list_presets() if p.name == name), None)

    def list_requests(self) -> list[sample_data.AppRequest]:
        return sorted(sample_data.REQUESTS, key=lambda r: r.when, reverse=True)

    def pending_requests(self, machine: str | None = None) -> list[sample_data.AppRequest]:
        return [r for r in self.list_requests()
                if r.status is sample_data.RequestStatus.PENDING and machine in (None, r.machine)]

    def approve_request(self, request_id: int) -> sample_data.AppRequest:
        """Approving deploys the app for real, even though the request itself is local."""
        request = self._request(request_id)
        request.status = sample_data.RequestStatus.APPROVED
        self.add_apps([request.machine], [request.app])
        return request

    def decline_request(self, request_id: int) -> sample_data.AppRequest:
        request = self._request(request_id)
        request.status = sample_data.RequestStatus.DECLINED
        return request

    def create_request(
        self, machine: str, app: str, requested_by: str, reason: str
    ) -> sample_data.AppRequest:
        request = sample_data.AppRequest(
            id=max((r.id for r in sample_data.REQUESTS), default=0) + 1,
            machine=machine, app=app, requested_by=requested_by,
            when=datetime.now(), reason=reason,
        )
        sample_data.REQUESTS.append(request)
        return request

    def _request(self, request_id: int) -> sample_data.AppRequest:
        return next(r for r in sample_data.REQUESTS if r.id == request_id)

    def current_update(self) -> sample_data.Update:
        return sample_data.CURRENT_UPDATE
