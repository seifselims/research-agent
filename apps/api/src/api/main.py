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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    # On shutdown, close every pooled connection so Postgres doesn't hold them open.
    await engine.dispose()


app = FastAPI(title="Research Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@app.get("/health")
async def health(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
