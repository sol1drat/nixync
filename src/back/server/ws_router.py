import sqlite3

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import database
from models import ApplyConfigOut, ApplyResultIn, ConfigReportIn, TelemetryIn

router = APIRouter()

UNKNOWN_MACHINE_CLOSE_CODE = 4404


@router.websocket("/ws/machines/{machine_id}")
async def machine_socket(websocket: WebSocket, machine_id: str) -> None:
    """Persistent agent connection: telemetry and config reports up, config pushes down."""
    conn: sqlite3.Connection = websocket.app.state.db
    connections = websocket.app.state.connections

    await websocket.accept()

    machine = database.get_machine(conn, machine_id)
    if machine is None:
        await websocket.close(code=UNKNOWN_MACHINE_CLOSE_CODE, reason="Unknown machine")
        return

    connections.register(machine_id, websocket)
    try:
        # An agent that was offline when a change was requested gets it on reconnect.
        if machine.last_apply_status == "pending" and machine.last_apply_id:
            await websocket.send_json(
                ApplyConfigOut(apply_id=machine.last_apply_id, config=machine.config).model_dump()
            )

        while True:
            _handle_message(conn, machine_id, await websocket.receive_json())
    except WebSocketDisconnect:
        pass
    finally:
        connections.unregister(machine_id)


def _handle_message(conn: sqlite3.Connection, machine_id: str, message: dict) -> None:
    match message.get("type"):
        case "telemetry":
            database.update_telemetry(
                conn, machine_id, **TelemetryIn.model_validate(message).model_dump()
            )
        case "config_report":
            # What the machine *has*, which is not the same as what it *should* have.
            database.save_reported_config(
                conn, machine_id, ConfigReportIn.model_validate(message).config
            )
        case "apply_result":
            # Mismatched apply_ids are acks for a push that a newer one already superseded.
            result = ApplyResultIn.model_validate(message)
            database.set_apply_result(
                conn,
                machine_id,
                apply_id=result.apply_id,
                status=result.status,
                message=result.message,
            )
