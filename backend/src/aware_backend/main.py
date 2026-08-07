from fastapi import FastAPI

from aware_backend.config import get_settings
from aware_backend.routers import auth, webrtc, ws

app = FastAPI(title="Aware Backend")
app.include_router(auth.router)
app.include_router(webrtc.router)
app.include_router(ws.router)


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }
