"""The admin side of the product: what the desktop GUI calls to manage a fleet.

Synchronous on purpose — a Qt app should run these off the UI thread (QThread or
QThreadPool), the same way it already treats `search_apps`. Everything that can go
wrong surfaces as a single `NixyncApiError`, so the GUI never has to know that
`requests` is underneath.
"""

from dataclasses import dataclass

import requests

from nixync_client.protocol import MachineConfig
from nixync_client.transport import NixyncClientError

DEFAULT_TIMEOUT_SECONDS = 5.0


class NixyncApiError(NixyncClientError):
    """A request to the server failed.

    `status_code` is the HTTP status, or None when no response arrived at all
    (server down, bad URL, DNS failure, timeout).
    """

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Machine:
    """One machine as the fleet dashboard sees it."""

    id: str
    name: str
    created_at: str
    online: bool
    config: MachineConfig
    reported_config: MachineConfig | None = None
    cpu_percent: float | None = None
    ram_used_mb: int | None = None
    ram_total_mb: int | None = None
    disk_used_gb: float | None = None
    disk_total_gb: float | None = None
    metrics_reported_at: str | None = None
    last_apply_id: str | None = None
    last_apply_status: str | None = None
    last_apply_message: str | None = None
    last_apply_at: str | None = None

    @property
    def has_drifted(self) -> bool:
        """True when the machine's actual setup differs from what the admin declared.

        False while the machine has never reported in — unknown is not drift.
        """
        return self.reported_config is not None and self.reported_config != self.config

    @classmethod
    def from_dict(cls, data: dict) -> "Machine":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=data["created_at"],
            online=data["online"],
            config=MachineConfig.from_dict(data.get("config") or {}),
            reported_config=(
                MachineConfig.from_dict(data["reported_config"])
                if data.get("reported_config") is not None
                else None
            ),
            cpu_percent=data.get("cpu_percent"),
            ram_used_mb=data.get("ram_used_mb"),
            ram_total_mb=data.get("ram_total_mb"),
            disk_used_gb=data.get("disk_used_gb"),
            disk_total_gb=data.get("disk_total_gb"),
            metrics_reported_at=data.get("metrics_reported_at"),
            last_apply_id=data.get("last_apply_id"),
            last_apply_status=data.get("last_apply_status"),
            last_apply_message=data.get("last_apply_message"),
            last_apply_at=data.get("last_apply_at"),
        )


@dataclass(frozen=True)
class PackageChangeResult:
    """What happened to one machine in a package change.

    `delivery` is `pushed` (sent to a connected agent), `queued` (delivered when it
    reconnects) or `unchanged` (already in this exact state, nothing to do).
    """

    machine_id: str
    delivery: str
    apply_id: str

    @property
    def needs_deployment(self) -> bool:
        return self.delivery != "unchanged"


class AdminClient:
    """Fleet management calls for the Nixync host application."""

    def __init__(
        self,
        server_url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
    ):
        self.base_url = server_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    # -- machines ----------------------------------------------------------

    def get_status(self) -> dict:
        """Whether the server is reachable — what the status bar polls."""
        return self._request("GET", "/status")

    def register_machine(self, name: str) -> Machine:
        """Add a machine to the fleet. The returned id is what its agent connects with."""
        return Machine.from_dict(self._request("POST", "/machines", json={"name": name}))

    def list_machines(self) -> list[Machine]:
        return [Machine.from_dict(item) for item in self._request("GET", "/machines")]

    def get_machine(self, machine_id: str) -> Machine:
        return Machine.from_dict(self._request("GET", f"/machines/{machine_id}"))

    def find_machine_by_name(self, name: str) -> Machine | None:
        """Look a machine up the way the GUI refers to it.

        The server does not enforce unique names, so an ambiguous name raises rather
        than silently picking one — acting on the wrong machine is worse than failing.
        """
        matches = [machine for machine in self.list_machines() if machine.name == name]
        if len(matches) > 1:
            raise NixyncApiError(f"more than one machine is named {name!r}")
        return matches[0] if matches else None

    def remove_machine(self, machine_id: str) -> None:
        self._request("DELETE", f"/machines/{machine_id}")

    # -- package changes ---------------------------------------------------

    def change_packages(
        self,
        action: str,
        packages: list[str],
        machine_ids: list[str] | None = None,
    ) -> list[PackageChangeResult]:
        """Add or remove packages. `machine_ids=None` targets the whole fleet."""
        payload = {"action": action, "packages": packages, "machine_ids": machine_ids}
        response = self._request("POST", "/machines/packages", json=payload)
        return [PackageChangeResult(**item) for item in response["results"]]

    def add_packages(
        self, packages: list[str], machine_ids: list[str] | None = None
    ) -> list[PackageChangeResult]:
        return self.change_packages("add", packages, machine_ids)

    def remove_packages(
        self, packages: list[str], machine_ids: list[str] | None = None
    ) -> list[PackageChangeResult]:
        return self.change_packages("remove", packages, machine_ids)

    # -- plumbing ----------------------------------------------------------

    def _request(self, method: str, path: str, json: dict | None = None):
        try:
            response = self.session.request(
                method, f"{self.base_url}{path}", json=json, timeout=self.timeout
            )
        except requests.RequestException as error:
            raise NixyncApiError(f"could not reach the Nixync server: {error}") from error

        if not response.ok:
            raise NixyncApiError(
                f"{method} {path} failed: {_detail_of(response)}",
                status_code=response.status_code,
            )
        return None if response.status_code == 204 else response.json()


def _detail_of(response: requests.Response) -> str:
    """FastAPI puts the useful part in `detail`; fall back to the raw body."""
    try:
        body = response.json()
    except ValueError:
        return response.text or f"HTTP {response.status_code}"
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return detail if isinstance(detail, str) else str(detail)
