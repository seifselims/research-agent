"""FastAPI application entry point. Run with: uv run uvicorn api.main:app --reload"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.db import engine, get_session
from api.errors import UnhandledErrorMiddleware, register_error_handlers
from api.schemas import ErrorResponse

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # On shutdown, close every pooled connection so Postgres doesn't hold them open.
    await engine.dispose()


def create_app() -> FastAPI:
    """Build the app. A function (not just a global) so tests can create fresh copies."""
    app = FastAPI(
        title="Research Agent API",
        lifespan=lifespan,
        # Shown in /docs: every endpoint can return these, in the standard error shape.
        responses={
            422: {"model": ErrorResponse, "description": "Invalid request"},
            500: {"model": ErrorResponse, "description": "Unexpected server error"},
        },
    )

    register_error_handlers(app)

    # Order matters: the middleware added LAST runs FIRST (outermost). CORS is added after the
    # safety net so that even 500 responses get CORS headers and the browser lets the frontend
    # read them.
    app.add_middleware(UnhandledErrorMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health(session: SessionDep) -> dict[str, str]:
        await session.execute(text("SELECT 1"))
        return {"status": "ok", "database": "ok"}

    return app


app = create_app()
