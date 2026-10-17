"""App requests: someone at a machine asking for software they cannot install.

The point of a managed fleet is that a user cannot install whatever they like, so a
request has to reach an admin and wait for a decision. Approving deploys the package
through the same path as any other change, which means it queues for a machine that
is switched off rather than being lost.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

import database
from connection_manager import ConnectionManager
from machines_router import _apply_action, _deploy, get_connections, get_db
from models import AppRequest, AppRequestCreate

router = APIRouter(prefix="/requests", tags=["requests"])


@router.get("", response_model=list[AppRequest])
def list_requests(
    machine_id: str | None = None, conn: sqlite3.Connection = Depends(get_db)
) -> list[AppRequest]:
    """Every request, newest first. `?machine_id=` narrows it to one device."""
    return database.list_requests(conn, machine_id)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=AppRequest)
def create_request(
    payload: AppRequestCreate, conn: sqlite3.Connection = Depends(get_db)
) -> AppRequest:
    """Record an ask from a device. Deploys nothing on its own."""
    if database.get_machine(conn, payload.machine_id) is None:
        raise HTTPException(status_code=404, detail=f"Machine not found: {payload.machine_id}")
    return database.create_request(
        conn,
        machine_id=payload.machine_id,
        app=payload.app,
        requested_by=payload.requested_by,
        reason=payload.reason,
    )


def _decided(conn: sqlite3.Connection, request_id: int) -> AppRequest:
    request = database.get_request(conn, request_id)
    if request is None:
        raise HTTPException(status_code=404, detail=f"Request not found: {request_id}")
    if request.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Request {request_id} was already {request.status}.",
        )
    return request


@router.post("/{request_id}/approve", response_model=AppRequest)
async def approve_request(
    request_id: int,
    conn: sqlite3.Connection = Depends(get_db),
    connections: ConnectionManager = Depends(get_connections),
) -> AppRequest:
    """Mark it approved and deploy the app to that machine.

    Deciding twice is refused rather than redeployed: a second approval would be a
    double click, and the admin has no way to tell it did nothing.
    """
    request = _decided(conn, request_id)
    machine = database.get_machine(conn, request.machine_id)
    if machine is None:
        raise HTTPException(
            status_code=409,
            detail=f"{request.machine_name} is no longer in the fleet.",
        )

    await _deploy(conn, connections, machine, _apply_action(machine.config, "add", [request.app]))
    return database.set_request_status(conn, request_id, "approved")


@router.post("/{request_id}/decline", response_model=AppRequest)
def decline_request(
    request_id: int, conn: sqlite3.Connection = Depends(get_db)
) -> AppRequest:
    """Mark it declined. Nothing is deployed."""
    _decided(conn, request_id)
    return database.set_request_status(conn, request_id, "declined")
