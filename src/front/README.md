# Nixync front end (Qt 6, PySide6)

Desktop app for the Nixync host. It talks to the Nixync FastAPI server over HTTP.
Screens follow the host app sketch: **Machines**, **Roles** and **Updates** in the
sidebar, with **Add machine** and **Undo update** as dialogs.

Sign-in, the device list, live telemetry, deploying apps and per-device system
settings are **real** — they go through `nixync_client` (`src/back/client`) to the
server. Presets, groups, app requests and the updates page still come from
`nixync_front/sample_data.py`, because the server has no data model for them yet.
See `SPEC.md` for the full split and the field mapping.

Sign in with **`admin` / `password`** (override with `NIXYNC_ADMIN_USER` and
`NIXYNC_ADMIN_PASSWORD` on the server). There is no authorization behind it — every
other endpoint is open, so treat this as a demo gate, not security.

## Trying it across two machines

One machine runs the server and this app; the other runs an agent.

```sh
# machine A — the server, bound so the other machine can reach it
cd src/back/server
NIXYNC_DB=nixync.db python -m uvicorn server:app --host 0.0.0.0 --port 8000

# machine A — the host app; sign in and point it at the server
cd src/front && NIXYNC_SERVER_URL=http://<machine-A-ip>:8000 python -m nixync_front
```

Add the device in the app. The status bar then shows its **agent id** — the server
mints it, and there is no provisioning channel yet, so copy it across by hand:

```sh
# machine B — the managed NixOS box
python src/back/client/example_agent.py \
    --server http://<machine-A-ip>:8000 --machine-id <agent-id>
```

The device turns Online with live CPU, memory and disk. Apps you add from the app
reach it over its socket; a device that is switched off gets the change when it next
connects. Note the reference agent **prints** what it would install rather than
touching the system — give `example_agent.py` a real `apply_config` to make
deployments actually change the machine.

## Run

Python 3.11+ is required (uses `tomllib`).

```sh
cd src/front
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m nixync_front
```

## Configure the server

The app reads `src/front/config.toml` if it exists (copy `config.example.toml`).
Environment variables override it:

| Variable | Meaning | Default |
|---|---|---|
| `NIXYNC_SERVER_URL` | Base URL of the FastAPI server | `http://127.0.0.1:8000` |
| `NIXYNC_CONFIG` | Path to a different config file | `src/front/config.toml` |

The status bar polls `GET /status` every `poll_interval_seconds` and shows whether
the server is reachable. To try it against the existing server:

```sh
# terminal 1
pip install fastapi uvicorn
uvicorn server:app --app-dir src/back/server --port 8000

# terminal 2
cd src/front && python -m nixync_front
```

## Layout

```
nixync_front/
  app.py            QApplication setup, entry point
  main_window.py    sidebar + stacked pages, server status polling
  api.py            NixyncClient (HTTP client for the FastAPI server)
  config.py         config.toml / env loading
  sample_data.py    placeholder fleet data
  style.py          colors and the Qt stylesheet
  widgets.py        small shared widgets
  pages/            Machines, Roles, Updates
  dialogs/          Add machine, Undo update
```

## Headless check

```sh
QT_QPA_PLATFORM=offscreen python -c "from PySide6.QtWidgets import QApplication; \
from nixync_front.main_window import MainWindow; from nixync_front.config import load_config; \
app = QApplication([]); MainWindow(load_config()).show(); print('ok')"
```
