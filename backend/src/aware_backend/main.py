from fastapi import FastAPI

from aware_backend.config import get_settings

app = FastAPI(title="Aware Backend")


@app.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {
        "status": "ok",
        "version": settings.app_version,
        "environment": settings.environment,
    }
