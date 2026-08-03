import asyncio
import uuid

import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import VideoStreamTrack
from av.video.frame import VideoFrame
from httpx import AsyncClient

from aware_backend.webrtc import get_frame_buffer


class _SyntheticVideoTrack(VideoStreamTrack):
    async def recv(self) -> VideoFrame:
        pts, time_base = await self.next_timestamp()
        array = np.zeros((480, 640, 3), dtype=np.uint8)
        frame = VideoFrame.from_ndarray(array, format="bgr24")
        frame.pts = pts
        frame.time_base = time_base
        return frame


async def _signed_up_access_token(client: AsyncClient) -> str:
    email = f"webrtc-{uuid.uuid4().hex[:12]}@example.com"
    response = await client.post(
        "/auth/signup", json={"email": email, "password": "correct horse battery staple"}
    )
    token: str = response.json()["access_token"]
    return token


async def test_webrtc_offer_negotiates_and_samples_video(client: AsyncClient) -> None:
    access_token = await _signed_up_access_token(client)

    pc = RTCPeerConnection()
    pc.addTrack(_SyntheticVideoTrack())
    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        response = await client.post(
            "/webrtc/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["session_id"]

        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))

        for _ in range(20):
            if pc.connectionState in ("connected", "completed"):
                break
            await asyncio.sleep(0.5)
        assert pc.connectionState in ("connected", "completed")

        for _ in range(20):
            buffer = get_frame_buffer(body["session_id"])
            if buffer is not None and buffer.frame_count > 0:
                break
            await asyncio.sleep(0.5)
        assert buffer is not None
        assert buffer.frame_count > 0
        assert buffer.latest_frame is not None
        assert buffer.latest_frame.width == 640
        assert buffer.latest_frame.height == 480
    finally:
        await pc.close()


async def test_webrtc_offer_without_token_rejected(client: AsyncClient) -> None:
    pc = RTCPeerConnection()
    pc.addTrack(_SyntheticVideoTrack())
    try:
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        response = await client.post(
            "/webrtc/offer",
            json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type},
        )
        assert response.status_code in (401, 403)
    finally:
        await pc.close()
