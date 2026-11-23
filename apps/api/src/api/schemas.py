"""Pydantic schemas: the shapes of JSON the API accepts (requests) and returns (responses).

Kept separate from models.py on purpose: models are database tables, schemas are the public API.
A response only ever contains the fields listed here, so internal columns can't leak by accident.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from api.models import JobStatus


class RequestSchema(BaseModel):
    # forbid: unknown fields are a validation error instead of being silently ignored.
    # str_strip_whitespace: "  fasting  " becomes "fasting" before length checks run.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseSchema(BaseModel):
    # from_attributes: build a response directly from a SQLAlchemy object,
    # e.g. JobResponse.model_validate(job).
    model_config = ConfigDict(from_attributes=True)


# --- Errors (documents the shape produced by errors.py, for /docs and the frontend) --------------


class ErrorBody(BaseModel):
    code: str = Field(examples=["not_found"])
    message: str = Field(examples=["Job not found"])
    details: Any = None


class ErrorResponse(BaseModel):
    error: ErrorBody


# --- Jobs -----------------------------------------------------------------------------------------


class CreateJobRequest(RequestSchema):
    query: str = Field(
        min_length=3,
        max_length=500,
        description="The research question.",
        examples=["What are the health effects of intermittent fasting?"],
    )


class JobResponse(ResponseSchema):
    id: uuid.UUID
    query: str
    status: JobStatus
    error: str | None
    created_at: datetime
    updated_at: datetime


# --- Reports --------------------------------------------------------------------------------------


class SourceResponse(ResponseSchema):
    id: uuid.UUID
    url: str
    title: str | None


class ReportSummary(ResponseSchema):
    """One item in "list reports": no content, so the list stays small."""

    id: uuid.UUID
    job_id: uuid.UUID
    title: str
    created_at: datetime


class ReportResponse(ReportSummary):
    """A full report with its sources."""

    content: str
    sources: list[SourceResponse]


class ReportListResponse(BaseModel):
    items: list[ReportSummary]
    # Opaque cursor for the next page, or None on the last page.
    next_cursor: str | None = None
