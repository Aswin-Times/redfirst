"""Request/response contracts for the HTTP API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from redfirst.analysis.report import BugReportInput


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    created_at: datetime


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    project_id: str
    source_type: str
    sha256: str | None
    layout: dict[str, Any] | None
    created_at: datetime


class InvestigationIn(BaseModel):
    repository_id: str
    bug_report: BugReportInput


class InvestigationOut(BaseModel):
    id: str
    project_id: str
    repository_id: str
    title: str
    state: str
    outcome: str | None
    outcome_reason: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
