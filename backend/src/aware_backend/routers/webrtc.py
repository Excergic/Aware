from fastapi import APIRouter, status

from aware_backend.deps import CurrentUser, DbSession
from aware_backend.models import Session as SessionModel
from aware_backend.routers.ws import get_ws_sender
from aware_backend.schemas import WebRTCAnswer, WebRTCOffer
from aware_backend.webrtc import create_peer_connection

router = APIRouter(prefix="/webrtc", tags=["webrtc"])


@router.post("/offer", response_model=WebRTCAnswer, status_code=status.HTTP_201_CREATED)
async def offer(
    payload: WebRTCOffer, current_user: CurrentUser, db: DbSession
) -> WebRTCAnswer:
    session = SessionModel(user_id=current_user.id)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    session_key = str(session.id)
    answer = await create_peer_connection(
        sdp=payload.sdp,
        sdp_type=payload.type,
        session_key=session_key,
        send_audio=get_ws_sender(session_key),
    )

    return WebRTCAnswer(sdp=answer.sdp, type=answer.type, session_id=session.id)
