from __future__ import annotations

from fastapi import APIRouter, WebSocket

router = APIRouter(tags=["communication"])


@router.websocket("/api/communication")
async def communication(websocket: WebSocket) -> None:
    """Stream live SIRI producer/consumer XML communication."""
    await websocket.app.state.services.communication_monitor.serve(websocket)
