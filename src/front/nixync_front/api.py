"""Thin client for the Nixync FastAPI server.

Only GET /status exists on the server today. The other methods are the
calls the UI expects; they return sample data until the server grows them.
"""

import requests

from nixync_front import sample_data
from nixync_front.config import Config


class ApiError(Exception):
    pass


class NixyncClient:
    def __init__(self, config: Config):
        self.base_url = config.server_url
        self.timeout = config.request_timeout
        self.session = requests.Session()

    def _get(self, path: str):
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            raise ApiError(str(e)) from e

    def get_status(self) -> dict:
        return self._get("/status")

    # TODO: replace with GET /machines once the server has it.
    def list_machines(self) -> list[sample_data.Machine]:
        return list(sample_data.MACHINES)

    # TODO: replace with GET /roles once the server has it.
    def list_roles(self) -> list[sample_data.Role]:
        return list(sample_data.ROLES)

    # TODO: replace with GET /updates/current once the server has it.
    def current_update(self) -> sample_data.Update:
        return sample_data.CURRENT_UPDATE
