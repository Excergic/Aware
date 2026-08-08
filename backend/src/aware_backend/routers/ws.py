"""WebSocket endpoint for streaming TTS audio back to the browser.

The browser connects here after receiving a session_id from POST /webrtc/offer.
The VoicePipeline in voice.py calls send_audio_to_session() to push PCM chunks
back through this connection.
"""

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])

# session_id → active WebSocket (populated when browser connects)
_sessions: dict[str, WebSocket] = {}


def get_ws_sender(session_id: str):  # type: ignore[no-untyped-def]
    """Return an async callable that sends bytes to the browser, or None if not connected."""

    async def _send(data: bytes) -> None:
        ws = _sessions.get(session_id)
        if ws is not None:
            try:
                await ws.send_bytes(data)
            except Exception:
                _sessions.pop(session_id, None)

    return _send


@router.websocket("/ws/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    _sessions[session_id] = websocket
    logger.info("session=%s browser WebSocket connected", session_id)
    try:
        while True:
            # Keep the connection alive; browser may send pings or close frames.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _sessions.pop(session_id, None)
        logger.info("session=%s browser WebSocket disconnected", session_id)
