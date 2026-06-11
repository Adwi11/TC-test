import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routes.candidates import router as candidates_router


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run DB init on startup and quiet shutdown."""
    try:
        await init_db()
        log.info("db initialised")
    except Exception as e:
        log.warning("db init skipped: %s", e)
    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title="Resume Parsing & Document-Collection Agent", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_origin_regex=settings.cors_origin_regex or None,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(candidates_router)

    @app.get("/health")
    async def health() -> dict:
        """Simple liveness probe."""
        return {"ok": True}

    return app
