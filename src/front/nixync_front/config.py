import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path


def _default_path() -> Path:
    """Where config.toml lives.

    Running from the repository that is src/front/config.toml, next to the package.
    In a PyInstaller build the package sits in an _internal directory nobody would
    think to look in, so use the directory holding the executable instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config.toml"
    return Path(__file__).resolve().parent.parent / "config.toml"


DEFAULT_PATH = _default_path()


@dataclass(frozen=True)
class Config:
    server_url: str = "http://127.0.0.1:8000"
    request_timeout: float = 3.0
    poll_interval_seconds: int = 10
    # search.nixos.org index: latest-<schema version>-nixos-<channel>
    nixos_search_index: str = "latest-51-nixos-26.05"


def load_config() -> Config:
    path = Path(os.environ.get("NIXYNC_CONFIG", DEFAULT_PATH))
    values = {}
    if path.is_file():
        with path.open("rb") as f:
            values = tomllib.load(f)

    if url := os.environ.get("NIXYNC_SERVER_URL"):
        values["server_url"] = url

    known = Config.__dataclass_fields__
    config = Config(**{k: v for k, v in values.items() if k in known})
    return Config(
        server_url=config.server_url.rstrip("/"),
        request_timeout=float(config.request_timeout),
        poll_interval_seconds=int(config.poll_interval_seconds),
        nixos_search_index=config.nixos_search_index,
    )
