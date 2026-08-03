import asyncio
import logging
import time
from dataclasses import dataclass

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamTrack
from av.video.frame import VideoFrame

from aware_backend.config import get_settings

logger = logging.getLogger(__name__)

_peer_connections: dict[str, RTCPeerConnection] = {}


@dataclass
class FrameBuffer:
    latest_frame: VideoFrame | None = None
    frame_count: int = 0
    last_sampled_at: float = 0.0


_frame_buffers: dict[str, FrameBuffer] = {}


def get_frame_buffer(session_key: str) -> FrameBuffer | None:
    return _frame_buffers.get(session_key)


async def _consume_video(track: MediaStreamTrack, session_key: str) -> None:
    settings = get_settings()
    buffer = _frame_buffers.setdefault(session_key, FrameBuffer())
    while True:
        try:
            frame = await track.recv()
        except Exception:
            break
        if not isinstance(frame, VideoFrame):
            continue
        now = time.monotonic()
        if now - buffer.last_sampled_at >= settings.frame_sample_interval_seconds:
            buffer.latest_frame = frame
            buffer.frame_count += 1
            buffer.last_sampled_at = now
            logger.info(
                "session=%s sampled video frame #%d (%dx%d)",
                session_key,
                buffer.frame_count,
                frame.width,
                frame.height,
            )


async def _consume_audio(track: MediaStreamTrack, session_key: str) -> None:
    while True:
        try:
            await track.recv()
        except Exception:
            break


async def create_peer_connection(
    sdp: str, sdp_type: str, session_key: str
) -> RTCSessionDescription:
    settings = get_settings()
    configuration = RTCConfiguration(iceServers=[RTCIceServer(urls=[settings.stun_server])])
    pc = RTCPeerConnection(configuration=configuration)
    _peer_connections[session_key] = pc

    @pc.on("connectionstatechange")
    async def on_connectionstatechange() -> None:
        logger.info("session=%s connection state: %s", session_key, pc.connectionState)
        if pc.connectionState in ("failed", "closed", "disconnected"):
            await pc.close()
            _peer_connections.pop(session_key, None)
            _frame_buffers.pop(session_key, None)

    @pc.on("track")
    def on_track(track: MediaStreamTrack) -> None:
        logger.info("session=%s received track: %s", session_key, track.kind)
        if track.kind == "video":
            asyncio.ensure_future(_consume_video(track, session_key))
        elif track.kind == "audio":
            asyncio.ensure_future(_consume_audio(track, session_key))

    offer = RTCSessionDescription(sdp=sdp, type=sdp_type)
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    local_description = pc.localDescription
    assert local_description is not None
    return local_description
