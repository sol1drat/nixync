"""Reusable roles that machines can be assigned to.

A preset is metadata: assigning one labels a machine and tells the admin what it is
meant to be. It does not itself deploy anything — rolling a preset's apps out is a
separate, explicit action, so changing a label can never silently rebuild a fleet.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Response, status

import database
from machines_router import get_db
from models import Preset

router = APIRouter(prefix="/presets", tags=["presets"])


@router.get("", response_model=list[Preset])
def list_presets(conn: sqlite3.Connection = Depends(get_db)) -> list[Preset]:
    return database.list_presets(conn)


@router.get("/{name}", response_model=Preset)
def get_preset(name: str, conn: sqlite3.Connection = Depends(get_db)) -> Preset:
    preset = database.get_preset(conn, name)
    if preset is None:
        raise HTTPException(status_code=404, detail=f"Preset not found: {name}")
    return preset


@router.put("/{name}", response_model=Preset)
def save_preset(
    name: str, payload: Preset, conn: sqlite3.Connection = Depends(get_db)
) -> Preset:
    """Create or replace a preset.

    The name in the path wins over any name in the body, so a rename cannot happen
    by accident — that would silently orphan every machine pointing at the old one.
    """
    return database.save_preset(conn, payload.model_copy(update={"name": name}))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_preset(name: str, conn: sqlite3.Connection = Depends(get_db)) -> Response:
    in_use = database.machines_using_preset(conn, name)
    if in_use:
        raise HTTPException(
            status_code=409,
            detail=(
                f"{name} is still assigned to {', '.join(in_use)}. "
                "Move those machines to another preset first."
            ),
        )
    if not database.delete_preset(conn, name):
        raise HTTPException(status_code=404, detail=f"Preset not found: {name}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
