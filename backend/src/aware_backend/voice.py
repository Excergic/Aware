"""
Voice pipeline: Pulse STT → OpenAI vision LLM → Lightning TTS → WebSocket.

One VoicePipeline is created per WebRTC session.  It:
  1. Accepts av.AudioFrame objects from the WebRTC audio track.
  2. Resamples them to PCM16 @ 16 kHz and streams to Pulse STT over WebSocket.
  3. On each final transcript, calls OpenAI with a Socratic tutor prompt and
     the latest screen frame (if available).
  4. Streams the LLM reply through Lightning TTS and sends PCM audio back to
     the browser over the session's FastAPI WebSocket.
"""

import asyncio
import base64
import json
import logging
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import Any

import websockets
from av.audio.frame import AudioFrame
from av.audio.resampler import AudioResampler
from av.video.frame import VideoFrame
from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionContentPartImageParam,
    ChatCompletionContentPartTextParam,
    ChatCompletionMessageParam,
)
from smallestai import AsyncSmallestAI

from aware_backend.config import get_settings

logger = logging.getLogger(__name__)

_PULSE_STT_URL = (
    "wss://api.smallest.ai/waves/v1/stt/live"
    "?model=pulse&language=en&sample_rate=16000&encoding=linear16&eou_timeout_ms=1500"
)

_SYSTEM_PROMPT = """\
You are Aware, a Socratic pair-programmer and live screen-share tutor.
Your job is to help the user think — not to think for them.

Rules:
- NEVER give the answer directly. Instead, ask the single most useful clarifying
  question that guides the user one step closer to solving it themselves.
- If you can see the user's screen, reference what you see briefly and specifically.
- Keep every response short: one or two sentences max.
- Stay warm, curious, and encouraging.
- Respond in plain conversational English. No markdown formatting — your text will
  be spoken aloud as audio.
"""


def _frame_to_jpeg_b64(frame: VideoFrame) -> str:
    img = frame.to_image()  # type: ignore[no-untyped-call]
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=50)
    return base64.b64encode(buf.getvalue()).decode()


class VoicePipeline:
    """Manages the full STT → LLM → TTS loop for one WebRTC session."""

    def __init__(
        self,
        session_id: str,
        get_latest_frame: Callable[[], VideoFrame | None],
        send_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self._session_id = session_id
        self._get_latest_frame = get_latest_frame
        self._send_audio = send_audio

        settings = get_settings()
        self._stt_url = _PULSE_STT_URL
        self._stt_headers = {"Authorization": f"Bearer {settings.smallest_api_key}"}
        self._openai: AsyncOpenAI | None = (
            AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        )
        self._tts_client: AsyncSmallestAI | None = (
            AsyncSmallestAI(api_key=settings.smallest_api_key)
            if settings.smallest_api_key
            else None
        )
        self._settings = settings

        self._resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    async def push_audio_frame(self, frame: AudioFrame) -> None:
        resampled = self._resampler.resample(frame)
        for rf in resampled:
            pcm = rf.to_ndarray().tobytes()
            await self._audio_queue.put(pcm)

    async def stop(self) -> None:
        await self._audio_queue.put(None)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _run(self) -> None:
        try:
            async with websockets.connect(
                self._stt_url, additional_headers=self._stt_headers
            ) as ws:
                logger.info("session=%s Pulse STT connected", self._session_id)
                await asyncio.gather(
                    self._send_audio_to_stt(ws),
                    self._receive_transcripts(ws),
                )
        except Exception:
            logger.exception("session=%s voice pipeline error", self._session_id)

    async def _send_audio_to_stt(self, ws: Any) -> None:
        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                await ws.send(json.dumps({"type": "close_stream"}))
                break
            await ws.send(chunk)

    async def _receive_transcripts(self, ws: Any) -> None:
        async for raw in ws:
            if isinstance(raw, bytes):
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue

            transcript: str | None = event.get("transcript") or event.get("transcription")
            is_final: bool = bool(event.get("is_final") or event.get("is_last"))

            if is_final and transcript:
                logger.info(
                    "session=%s transcript: %s", self._session_id, transcript[:120]
                )
                asyncio.ensure_future(self._reply(transcript))

    async def _reply(self, user_text: str) -> None:
        try:
            response_text = await self._call_llm(user_text)
            await self._speak(response_text)
        except Exception:
            logger.exception("session=%s LLM/TTS reply error", self._session_id)

    async def _call_llm(self, user_text: str) -> str:
        assert self._openai is not None
        user_content: list[
            ChatCompletionContentPartTextParam | ChatCompletionContentPartImageParam
        ] = [ChatCompletionContentPartTextParam(type="text", text=user_text)]

        frame = self._get_latest_frame()
        if frame is not None:
            b64 = _frame_to_jpeg_b64(frame)
            user_content.append(
                ChatCompletionContentPartImageParam(
                    type="image_url",
                    image_url={"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
                )
            )

        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]

        response = await self._openai.chat.completions.create(
            model=self._settings.openai_model,
            messages=messages,
            max_tokens=200,
        )
        text: str = response.choices[0].message.content or ""
        logger.info("session=%s LLM response: %s", self._session_id, text[:120])
        return text

    async def _speak(self, text: str) -> None:
        assert self._tts_client is not None
        settings = self._settings
        async for chunk_b64 in await self._tts_client.waves.synthesize_sse_tts(
            text=text,
            voice_id=settings.tts_voice_id,
            sample_rate=settings.tts_sample_rate,
            output_format="pcm",
        ):
            try:
                payload = json.loads(chunk_b64)
                audio_b64: str | None = payload.get("audio")
                if audio_b64:
                    await self._send_audio(base64.b64decode(audio_b64))
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
