"""The app has to behave when it runs as a PyInstaller build, not just from the repo.

A frozen build is awkward to exercise in a unit test, so these pin the two things
that actually differ: where config.toml is looked for, and whether the sibling
packages the repository layout needs are still importable once they are bundled.
"""

import importlib
import sys
from pathlib import Path

from nixync_front import config


def test_config_is_read_from_beside_the_package_when_running_from_the_repo():
    assert config._default_path() == Path(config.__file__).resolve().parent.parent / "config.toml"


def test_config_is_read_from_beside_the_executable_when_frozen(monkeypatch, tmp_path):
    # In a build the package lives in an _internal directory; a user dropping a
    # config.toml there would never be found, so the executable's directory wins.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nixync"))

    assert config._default_path() == tmp_path / "config.toml"


def test_frozen_config_file_is_actually_loaded(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "nixync"))
    monkeypatch.delenv("NIXYNC_CONFIG", raising=False)
    monkeypatch.delenv("NIXYNC_SERVER_URL", raising=False)
    (tmp_path / "config.toml").write_text('server_url = "http://fleet.example:9000/"\n')

    # DEFAULT_PATH is computed at import time, so a build picks it up on startup.
    reloaded = importlib.reload(config)
    try:
        assert reloaded.load_config().server_url == "http://fleet.example:9000"
    finally:
        importlib.reload(config)


def test_missing_config_falls_back_to_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("NIXYNC_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.delenv("NIXYNC_SERVER_URL", raising=False)

    assert config.load_config().server_url == "http://127.0.0.1:8000"


def test_sibling_packages_the_build_bundles_are_importable():
    # The spec lists these as pathex/hiddenimports; if an import here breaks, the
    # bundle breaks at startup with a traceback no user can act on.
    for module in ("nixync_ui.style", "nixync_ui.widgets", "nixync_client.nix", "nixync_front.app"):
        assert importlib.import_module(module)


def test_icons_the_bundle_copies_exist_where_style_looks_for_them():
    import nixync_ui.style as style

    icons = Path(style.__file__).resolve().parent / "icons"
    assert icons.is_dir()
    assert (icons / "app-icon.png").is_file(), "the PyInstaller spec uses this as the executable icon"
