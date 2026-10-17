import sqlite3
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

import database
from connection_manager import ConnectionManager
from models import (
    ApplyConfigOut,
    MachineConfig,
    MachineCreate,
    MachineOut,
    MachineUpdate,
    PackageMutationRequest,
    PackageMutationResponse,
    PackageMutationResultItem,
    SettingsUpdate,
)

router = APIRouter(prefix="/machines", tags=["machines"])


def get_db(request: Request) -> sqlite3.Connection:
    return request.app.state.db


def get_connections(request: Request) -> ConnectionManager:
    return request.app.state.connections


def _with_online(machine: MachineOut, connections: ConnectionManager) -> MachineOut:
    return machine.model_copy(update={"online": connections.is_connected(machine.id)})


@router.post("", status_code=status.HTTP_201_CREATED, response_model=MachineOut)
def register_machine(
    payload: MachineCreate,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> MachineOut:
    machine = database.create_machine(
        conn,
        name=payload.name,
        preset=payload.preset,
        group=payload.group,
        address=payload.address,
    )
    return _with_online(machine, connections)


@router.get("", response_model=list[MachineOut])
def list_machines(
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> list[MachineOut]:
    return [_with_online(m, connections) for m in database.list_machines(conn)]


def _apply_action(config: MachineConfig, action: str, packages: list[str]) -> MachineConfig:
    if action == "add":
        updated = sorted(set(config.packages) | set(packages))
    else:
        updated = [p for p in config.packages if p not in set(packages)]
    return config.model_copy(update={"packages": updated})


def _already_satisfied(machine: MachineOut, desired: MachineConfig) -> bool:
    """True when the machine is provably already in the desired state.

    A machine whose last deployment failed or is still pending is not provably in its
    stored configuration, so it is redeployed even when the config happens to match.
    """
    return machine.last_apply_status == "applied" and machine.config == desired


@router.post("/packages", response_model=PackageMutationResponse)
async def change_packages(
    payload: PackageMutationRequest,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> PackageMutationResponse:
    """Apply a package change to selected machines, or to the whole fleet when no ids are given."""
    if payload.machine_ids is None:
        targets = database.list_machines(conn)
    else:
        targets = []
        for machine_id in payload.machine_ids:
            machine = database.get_machine(conn, machine_id)
            if machine is None:
                raise HTTPException(status_code=404, detail=f"Machine not found: {machine_id}")
            targets.append(machine)

    results = [
        await _deploy(
            conn,
            connections,
            machine,
            _apply_action(machine.config, payload.action, payload.packages),
        )
        for machine in targets
    ]
    return PackageMutationResponse(results=results)


async def _deploy(
    conn: sqlite3.Connection,
    connections: ConnectionManager,
    machine: MachineOut,
    desired: MachineConfig,
) -> PackageMutationResultItem:
    """Record a desired config and get it to the machine, now or on reconnect."""
    if _already_satisfied(machine, desired):
        return PackageMutationResultItem(
            machine_id=machine.id, delivery="unchanged", apply_id=machine.last_apply_id
        )

    apply_id = str(uuid.uuid4())
    database.set_apply_pending(conn, machine.id, apply_id=apply_id, config=desired)
    pushed = await connections.send_json(
        machine.id, ApplyConfigOut(apply_id=apply_id, config=desired).model_dump()
    )
    return PackageMutationResultItem(
        machine_id=machine.id,
        delivery="pushed" if pushed else "queued",
        apply_id=apply_id,
    )


@router.put("/{machine_id}/settings", response_model=PackageMutationResultItem)
async def save_settings(
    machine_id: str,
    payload: SettingsUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> PackageMutationResultItem:
    """Replace a machine's system settings and deploy them.

    The desktop app always sends the whole settings object, so this replaces rather
    than merges — otherwise a setting the operator turned off could never be removed.
    Packages and the rest of the config are untouched.
    """
    machine = database.get_machine(conn, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")

    desired = machine.config.model_copy(update={"settings": payload.settings})
    return await _deploy(conn, connections, machine, desired)


@router.patch("/{machine_id}", response_model=MachineOut)
def update_machine(
    machine_id: str,
    payload: MachineUpdate,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> MachineOut:
    """Edit a machine's name, preset, group or address.

    Labels only — nothing here changes what is deployed, so re-labelling a machine
    never triggers a rebuild. Assigning a preset that does not exist is rejected
    rather than stored, since a dangling label is just a typo nobody notices.
    """
    if database.get_machine(conn, machine_id) is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    if payload.preset and database.get_preset(conn, payload.preset) is None:
        raise HTTPException(status_code=404, detail=f"Preset not found: {payload.preset}")

    machine = database.update_machine(
        conn,
        machine_id,
        name=payload.name,
        preset=payload.preset,
        group=payload.group,
        address=payload.address,
    )
    return _with_online(machine, connections)


@router.get("/{machine_id}", response_model=MachineOut)
def get_machine(
    machine_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> MachineOut:
    machine = database.get_machine(conn, machine_id)
    if machine is None:
        raise HTTPException(status_code=404, detail="Machine not found")
    return _with_online(machine, connections)


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_machine(
    machine_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> Response:
    if not database.delete_machine(conn, machine_id):
        raise HTTPException(status_code=404, detail="Machine not found")
    await connections.close(machine_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
