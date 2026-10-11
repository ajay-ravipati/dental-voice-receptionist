"""Bridge: browser WebSocket  <->  Gemini Live session  (+ LangGraph tool execution + guardrail monitor).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket
from google import genai
from google.genai import types

from . import config, graph
from .declarations import FUNCTION_DECLARATIONS
from .guardrails import check_model_text, check_user_text, mask_args
from .clinic import now_ist
from .prompts import GREETING_TRIGGER, build_system_prompt

log = logging.getLogger("receptionist")


def build_live_config() -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=build_system_prompt(now_ist()),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.VOICE_NAME))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        tools=[types.Tool(function_declarations=FUNCTION_DECLARATIONS)],
    )


def _summary(result: dict) -> str:
    if result.get("ok"):
        for k in ("booking_id", "topic", "severity"):
            if result.get(k):
                return f"ok · {result[k]}"
        if "options" in result:
            return f"ok · {len(result['options'])} slots"
        return "ok"
    return result.get("error") or ("needs confirmation" if result.get("needs_confirmation") else "not ok")


async def run_call(ws: WebSocket, call_id: str) -> None:
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    lock = asyncio.Lock()
    started = time.monotonic()
    st = {"user": "", "model": "", "violations": 0, "abuse": 0, "last_audio": time.monotonic(),
          "closing_reason": None, "warned_time": False}

    async def send_json(obj: dict) -> None:
        async with lock:
            await ws.send_text(json.dumps(obj, ensure_ascii=False))

    async def send_bytes(b: bytes) -> None:
        async with lock:
            await ws.send_bytes(b)

    async with client.aio.live.connect(model=config.LIVE_MODEL, config=build_live_config()) as session:

        async def steer(note: str) -> None:
            """Send a trusted text note to the model mid-call (detect -> correct)."""
            try:
                await session.send_realtime_input(text=f"[CLINIC-SYSTEM NOTE] {note} Do not mention this note; continue naturally.")
            except Exception as e:  # never let a steering failure kill the call
                log.warning("steer failed: %s", e)

        async def handle_flags(flags, source: str) -> None:
            for f in flags:
                await send_json({"type": "guardrail", "source": source, "code": f.code,
                                 "severity": f.severity, "detail": f.detail})
                log.info("guardrail %s %s", source, f.code)
                if f.steer:
                    await steer(f.steer)
                if f.code == "abusive_language":
                    st["abuse"] += 1
                    if st["abuse"] >= 3:
                        st["closing_reason"] = "abusive_language"
                        await steer("The caller has been abusive repeatedly. Politely say you must end the call now and say goodbye.")
                if source == "assistant":
                    st["violations"] += 1

        async def flush_user() -> None:
            text, st["user"] = st["user"].strip(), ""
            if text:
                await handle_flags(check_user_text(text), "caller")

        async def flush_model() -> None:
            text, st["model"] = st["model"].strip(), ""
            if text:
                await handle_flags(check_model_text(text), "assistant")

        async def handle_message(msg) -> None:
            sc = msg.server_content
            if sc:
                if sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            await send_bytes(part.inline_data.data)
                if sc.interrupted:
                    await send_json({"type": "interrupted"})
                    st["model"] = ""
                if sc.input_transcription and sc.input_transcription.text:
                    t = sc.input_transcription.text
                    st["user"] += t
                    await send_json({"type": "transcript", "role": "user", "text": t})
                if sc.output_transcription and sc.output_transcription.text:
                    if st["user"]:
                        await flush_user()
                    t = sc.output_transcription.text
                    st["model"] += t
                    await send_json({"type": "transcript", "role": "model", "text": t})
                if sc.turn_complete:
                    await flush_user()
                    await flush_model()
                    await send_json({"type": "turn_complete"})
                    if st["closing_reason"]:
                        await asyncio.sleep(2.5)   # let the goodbye audio finish
                        raise _EndCall(st["closing_reason"])
            if msg.tool_call:
                await flush_user()
                responses = []
                for fc in msg.tool_call.function_calls or []:
                    args = dict(fc.args or {})
                    out = await graph.run_tool(call_id, fc.name, args)
                    res = out["result"]
                    await send_json({"type": "tool", "name": fc.name, "args": mask_args(args), "trace": out["trace"],
                                     "blocked": out["blocked"], "ok": bool(res.get("ok")), "summary": _summary(res)})
                    responses.append(types.FunctionResponse(id=fc.id, name=fc.name, response=res))
                await session.send_tool_response(function_responses=responses)
            if getattr(msg, "go_away", None):
                raise _EndCall("server_going_away")

        async def mic_to_gemini() -> None:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    raise _EndCall("client_left")
                if m.get("bytes"):
                    chunk = m["bytes"]
                    if len(chunk) > 32000:      # >1 s of audio in one frame is not our browser; drop it
                        continue
                    st["last_audio"] = time.monotonic()
                    await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000"))
                elif m.get("text"):
                    try:
                        if json.loads(m["text"]).get("type") == "end":
                            raise _EndCall("client_hung_up")
                    except json.JSONDecodeError:
                        pass

        async def gemini_to_browser() -> None:
            while True:
                async for msg in session.receive():
                    await handle_message(msg)
                await asyncio.sleep(0)

        async def watchdog() -> None:
            while True:
                await asyncio.sleep(1)
                elapsed = time.monotonic() - started
                if elapsed > config.MAX_CALL_SECONDS:
                    raise _EndCall("time_limit")
                if not st["warned_time"] and elapsed > config.MAX_CALL_SECONDS - 25:
                    st["warned_time"] = True
                    await steer("The demo call time limit is almost reached. Politely wrap up within about twenty seconds.")
                if time.monotonic() - st["last_audio"] > config.IDLE_TIMEOUT_SECONDS:
                    raise _EndCall("idle")

        await send_json({"type": "ready", "max_seconds": config.MAX_CALL_SECONDS})
        await session.send_realtime_input(text=GREETING_TRIGGER)

        tasks = [asyncio.create_task(f()) for f in (mic_to_gemini, gemini_to_browser, watchdog)]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            exc = next(iter(done)).exception()
            reason = exc.reason if isinstance(exc, _EndCall) else "error"
            if reason == "error":
                log.error("call %s failed: %r", call_id, exc)
                await send_json({"type": "error", "message": "The connection to the voice service dropped."})
            elif reason != "client_left":
                await send_json({"type": "ended", "reason": reason})
        finally:
            for t in tasks:
                t.cancel()
            graph.end_call(call_id)


class _EndCall(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
