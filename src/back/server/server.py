import os
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

import database
import machines_router
import presets_router
import ws_router
from connection_manager import ConnectionManager
from models import LoginRequest, LoginResponse

DEFAULT_DB_PATH = "nixync.db"
DEFAULT_ADMIN_USER = "admin"
DEFAULT_ADMIN_PASSWORD = "password"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = database.init_db(os.environ.get("NIXYNC_DB", DEFAULT_DB_PATH))
    app.state.connections = ConnectionManager()
    yield
    app.state.db.close()


API_DESCRIPTION = """
Control center API for managing a fleet of NixOS machines.

Two kinds of client talk to this server:

* **Admin clients** (the Nixync desktop UI) use the REST endpoints documented below.
* **Machine agents** keep one persistent WebSocket open for their whole lifetime.

## Agent WebSocket protocol

Endpoint: `ws://<server>/ws/machines/{machine_id}` — not listed below because OpenAPI has
no WebSocket representation. An unregistered `machine_id` is closed with code **4404**;
register the machine over REST first. Every frame is a JSON object with a `type` field.

**Agent to server**

| `type` | Fields | Sent when |
|---|---|---|
| `telemetry` | `cpu_percent`, `ram_used_mb`, `ram_total_mb`, `disk_used_gb`, `disk_total_gb` | Every 2 minutes |
| `config_report` | `config` (a MachineConfig) | Right after connecting, and again after every `apply_result` |
| `apply_result` | `apply_id`, `status` (`applied`/`failed`), `message` | After acting on an `apply_config` |

**Server to agent**

| `type` | Fields | Sent when |
|---|---|---|
| `apply_config` | `apply_id`, `config` (a MachineConfig) | A package change targets this machine, and again on reconnect while the change is still `pending` |

`apply_config` always carries the **full desired configuration**, never a diff — the agent
reconciles its whole state, so it cannot drift. An `apply_result` whose `apply_id` no
longer matches the machine's current one is a stale ack and is ignored.

## Desired vs reported configuration

A machine has two configurations, and they are deliberately separate:

* `config` — what the admin **declared**. Only admin actions change it.
* `reported_config` — what the machine says it **actually has**. `null` until it first
  reports in.

The first report from a machine that has never been deployed to is also adopted as its
desired config, so an existing machine joins the fleet with its setup intact. After
that, a report only updates `reported_config`; a difference between the two means
someone changed the box outside Nixync — configuration drift the fleet view can surface.
"""

app = FastAPI(
    title="Nixync Fleet Server",
    description=API_DESCRIPTION,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(machines_router.router)
app.include_router(presets_router.router)
app.include_router(ws_router.router)


@app.post("/login", response_model=LoginResponse, tags=["server"])
def login(credentials: LoginRequest) -> LoginResponse:
    """Check a single hardcoded operator account.

    This MVP has no authorization: every other endpoint is open, and nothing checks a
    session afterwards. The endpoint exists so the desktop app's sign-in screen fails
    honestly — wrong password, or server unreachable — rather than waving everyone
    through locally. Issuing a token nothing verifies would only look like security.
    """
    expected_user = os.environ.get("NIXYNC_ADMIN_USER", DEFAULT_ADMIN_USER)
    expected_password = os.environ.get("NIXYNC_ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)

    if credentials.username != expected_user or credentials.password != expected_password:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    return LoginResponse(username=credentials.username)


@app.get("/status", tags=["server"])
def get_status():
    with open("/proc/uptime", encoding="utf-8") as f:
        uptime = int(float(f.read().split()[0]))

    return {
        "hostname": socket.gethostname(),
        "status": "online",
        "uptime_seconds": uptime,
    }