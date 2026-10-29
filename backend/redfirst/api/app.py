"""FastAPI application factory."""

from fastapi import FastAPI

from redfirst.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="REDFIRST", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    return app


app = create_app()
