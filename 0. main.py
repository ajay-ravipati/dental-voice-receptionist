import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, limits
from .live_session import run_call

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("receptionist")

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="SmileCraft voice receptionist (demo)")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/health")
async def health():
    return {"ok": True, "model": config.LIVE_MODEL, "api_key_configured": bool(config.GEMINI_API_KEY)}


@app.get("/config")
async def public_config():
    return JSONResponse({"max_seconds": config.MAX_CALL_SECONDS})


def _client_ip(ws: WebSocket) -> str:
    fwd = ws.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return ws.client.host if ws.client else "unknown"


@app.websocket("/ws")
async def ws_call(ws: WebSocket):
    await ws.accept()
    origin = ws.headers.get("origin", "")
    if config.ALLOWED_ORIGINS and origin and origin not in config.ALLOWED_ORIGINS:
        await ws.send_json({"type": "error", "message": "This origin isn't allowed."})
        await ws.close(code=1008)
        return
    if not config.GEMINI_API_KEY:
        await ws.send_json({"type": "error", "message": "Server is missing GEMINI_API_KEY."})
        await ws.close(code=1011)
        return
    ok, reason = limits.try_acquire(_client_ip(ws))
    if not ok:
        await ws.send_json({"type": "error", "message": reason})
        await ws.close(code=1013)
        return
    call_id = uuid.uuid4().hex[:12]
    log.info("call %s started", call_id)
    try:
        await run_call(ws, call_id)
    except Exception as e:
        log.exception("call %s crashed", call_id)
        try:
            await ws.send_json({"type": "error", "message": "Couldn't reach the voice service. Check the API key and model name."})
        except Exception:
            pass
    finally:
        limits.release()
        log.info("call %s ended", call_id)
        try:
            await ws.close()
        except Exception:
            pass
