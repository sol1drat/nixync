# Nixync front end (Qt 6, PySide6)

Desktop app for the Nixync host. It talks to the Nixync FastAPI server over HTTP.
Screens follow the host app sketch: **Machines**, **Roles** and **Updates** in the
sidebar, with **Add machine** and **Undo update** as dialogs.

Only `GET /status` is real today; machines, roles and the current update come from
`nixync_front/sample_data.py` until the server has endpoints for them (see the
`TODO`s in `nixync_front/api.py`).

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
