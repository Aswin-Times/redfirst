"""FastAPI application factory.

No authentication: the MVP is single-user and binds to 127.0.0.1 by default. Do not expose
it on a shared network without adding auth.
"""

from fastapi import FastAPI
from sqlalchemy import Engine

from redfirst.api.routes import router
from redfirst.core.config import Settings, get_settings
from redfirst.db.session import make_engine
from redfirst.storage.blobs import BlobStore


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="REDFIRST", version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine or make_engine(settings.database_url)
    app.state.blobs = BlobStore(settings.data_dir / "blobs")
    app.include_router(router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "env": settings.env}

    return app
