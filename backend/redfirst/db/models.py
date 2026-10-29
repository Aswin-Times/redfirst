"""SQLAlchemy models. Large payloads (archives, logs, JUnit XML) live in the blob store;
rows hold only references (``*_ref``) and truncated excerpts.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from redfirst.domain.enums import InvestigationState, Outcome, OutcomeReason, TestStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


def _enum(cls: type[StrEnum]) -> Enum:
    # Stored as VARCHAR (not a native PG enum) so adding values needs no ALTER TYPE.
    return Enum(cls, native_enum=False, length=40, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(20))  # "archive" | "local"
    storage_ref: Mapped[str] = mapped_column(String(500))  # blob-store key or local path
    sha256: Mapped[str | None] = mapped_column(String(64))
    layout: Mapped[dict[str, Any] | None] = mapped_column()  # RepoLayout.model_dump()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    expected_behavior: Mapped[str | None] = mapped_column(Text)
    actual_behavior: Mapped[str | None] = mapped_column(Text)
    reproduction_steps: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    missing_fields: Mapped[list[str]] = mapped_column(default=list)  # tracked, never invented
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Investigation(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    bug_report_id: Mapped[str] = mapped_column(ForeignKey("bug_reports.id"), index=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("repositories.id"), index=True)
    state: Mapped[InvestigationState] = mapped_column(
        _enum(InvestigationState), default=InvestigationState.CREATED, index=True
    )
    outcome: Mapped[Outcome | None] = mapped_column(_enum(Outcome))
    outcome_reason: Mapped[OutcomeReason | None] = mapped_column(_enum(OutcomeReason))
    error: Mapped[dict[str, Any] | None] = mapped_column()  # infrastructure failure details
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 onupdate=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list["InvestigationEvent"]] = relationship(
        back_populates="investigation", order_by="InvestigationEvent.id"
    )
    attempts: Mapped[list["Attempt"]] = relationship(
        back_populates="investigation", order_by="Attempt.number"
    )


class InvestigationEvent(Base):
    """Append-only audit log of state transitions; also the source for progress streaming."""

    __tablename__ = "investigation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    from_state: Mapped[InvestigationState | None] = mapped_column(_enum(InvestigationState))
    to_state: Mapped[InvestigationState] = mapped_column(_enum(InvestigationState))
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    investigation: Mapped[Investigation] = relationship(back_populates="events")


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (UniqueConstraint("investigation_id", "number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)  # 1-based, bounded by max_generation_attempts
    status: Mapped[str] = mapped_column(String(40), default="started")
    llm_metadata: Mapped[dict[str, Any] | None] = mapped_column()  # model, prompt_version, tokens
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    investigation: Mapped[Investigation] = relationship(back_populates="attempts")
    generated_test: Mapped["GeneratedTest | None"] = relationship(back_populates="attempt")
    executions: Mapped[list["ExecutionResult"]] = relationship(
        back_populates="attempt", order_by="ExecutionResult.run_index"
    )


class GeneratedTest(Base):
    __tablename__ = "generated_tests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), unique=True)
    code: Mapped[str] = mapped_column(Text)
    contract: Mapped[dict[str, Any] | None] = mapped_column()  # TestContract.model_dump()
    validation_result: Mapped[dict[str, Any] | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempt: Mapped[Attempt] = relationship(back_populates="generated_test")


class ExecutionResult(Base):
    __tablename__ = "execution_results"
    __table_args__ = (UniqueConstraint("attempt_id", "run_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), index=True)
    run_index: Mapped[int] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(default=False)
    oom_killed: Mapped[bool] = mapped_column(default=False)
    main_status: Mapped[TestStatus | None] = mapped_column(_enum(TestStatus))
    stdout_ref: Mapped[str | None] = mapped_column(String(500))
    stderr_ref: Mapped[str | None] = mapped_column(String(500))
    junit_ref: Mapped[str | None] = mapped_column(String(500))
    stdout_excerpt: Mapped[str | None] = mapped_column(Text)  # truncated; full text in blob
    parsed: Mapped[dict[str, Any] | None] = mapped_column()  # RunResult.model_dump()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    attempt: Mapped[Attempt] = relationship(back_populates="executions")


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(ForeignKey("investigations.id"), index=True)
    execution_result_id: Mapped[str | None] = mapped_column(ForeignKey("execution_results.id"))
    kind: Mapped[str] = mapped_column(String(40))  # traceback_frame | assertion | code_location ...
    payload: Mapped[dict[str, Any]] = mapped_column()
    artifact_ref: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
