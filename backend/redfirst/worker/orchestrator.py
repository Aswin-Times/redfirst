"""Drives one investigation through the state machine.

Every stage boundary is committed, so a crash or restart leaves an inspectable history.
The LLM produces candidate tests; the outcome comes only from ``verification.rules``.
"""

import logging
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine

from redfirst.analysis.index import index_repo
from redfirst.analysis.ranking import rank_files
from redfirst.analysis.report import BugReportInput, analyze_report, render_report
from redfirst.core.config import Settings
from redfirst.db import service
from redfirst.db.models import (
    Attempt,
    BugReport,
    EvidenceRecord,
    ExecutionResult,
    GeneratedTest,
    Investigation,
    Repository,
)
from redfirst.db.session import session_scope
from redfirst.domain.enums import InvestigationState as S
from redfirst.domain.enums import Outcome, OutcomeReason, TestPhase
from redfirst.domain.state_machine import is_terminal
from redfirst.generation.evidence import build_evidence
from redfirst.generation.generator import (
    execution_feedback,
    generate_once,
    rejection_feedback,
    to_contract,
)
from redfirst.llm.base import LLMProvider, LLMRefused, LLMRequest, attempt_metadata
from redfirst.llm.prompts import PromptTemplate
from redfirst.repos.extract import extract_archive
from redfirst.repos.layout import detect_layout
from redfirst.sandbox.executor import ExecRequest, Executor
from redfirst.sandbox.runner import SandboxRun
from redfirst.security.redact import redact
from redfirst.storage.blobs import BlobStore
from redfirst.validation.policy import module_map
from redfirst.verification.models import RunResult, Verdict
from redfirst.verification.rules import classify
from redfirst.worker.lease import LeaseKeeper

log = logging.getLogger(__name__)

_RETRY_AFTER_EXECUTION = (OutcomeReason.SETUP_FAILURE, OutcomeReason.CONTROL_FAILED)
_EXCERPT = 4_000
BLOCKED = "blocked"  # attempt status for an LLM call refused by REDFIRST's own budget


class Stopped(Exception):
    """The run was cancelled, finished or recovered elsewhere; stop without writing."""


Cancelled = Stopped  # previous name, kept for callers


@dataclass(frozen=True)
class Deps:
    settings: Settings
    engine: Engine
    blobs: BlobStore
    provider: LLMProvider
    executor: Executor
    prompt: PromptTemplate
    work_root: Path


@dataclass
class _Context:
    report: BugReportInput
    report_text: str
    expected_behavior_known: bool
    repo_dir: Path
    source_roots: tuple[str, ...]
    modules: dict[str, str]
    evidence_text: str


class Orchestrator:
    def __init__(self, deps: Deps, investigation_id: str, lease: LeaseKeeper | None = None) -> None:
        self.d = deps
        self.inv_id = investigation_id
        self.lease = lease
        self.work = deps.work_root / investigation_id

    # -- persistence helpers -----------------------------------------------------------------
    def _write_state(self, change) -> None:
        """Apply a state change unless the run was cancelled, finished or recovered elsewhere.

        ``change(session, inv)`` performs a compare-and-swap transition; if the row moved since
        it was read (``StaleState``) or the lease was lost, the worker stops without writing.
        """
        if self.lease is not None and self.lease.lost.is_set():
            raise Stopped("this worker's lease on the investigation was lost")
        try:
            with session_scope(self.d.engine) as s:
                inv = s.get(Investigation, self.inv_id)
                if inv is None or is_terminal(inv.state):
                    raise Stopped(f"investigation is {inv.state.value if inv else 'deleted'}")
                change(s, inv)
        except service.StaleState as exc:
            raise Stopped(f"investigation changed concurrently: {exc}") from exc

    def _advance(self, target: S, message: str = "", data: dict[str, Any] | None = None) -> None:
        self._write_state(lambda s, inv: service.transition(s, inv, target, message, data))

    def _complete(self, outcome: Outcome, reason: OutcomeReason, message: str = "") -> None:
        self._write_state(lambda s, inv: service.complete(s, inv, outcome, reason, message))

    def _fail(self, error: dict[str, Any], message: str = "") -> None:
        try:
            self._write_state(lambda s, inv: service.fail(s, inv, error, message))
        except Stopped as exc:  # whoever finished it first decided the outcome
            log.info("not failing %s: %s", self.inv_id, exc)

    def _evidence(self, kind: str, payload: dict[str, Any], execution_id: str | None = None,
                  artifact_ref: str | None = None) -> None:
        with session_scope(self.d.engine) as s:
            s.add(EvidenceRecord(investigation_id=self.inv_id, kind=kind, payload=payload,
                                 execution_result_id=execution_id, artifact_ref=artifact_ref))

    # -- entry point ---------------------------------------------------------------------------
    def run(self) -> None:
        """Run from ANALYZING_REPORT to a terminal state. Never raises for pipeline errors."""
        try:
            ctx = self._analyze()
            self._generate_execute_verify(ctx)
        except Stopped as exc:
            log.info("investigation %s stopped: %s", self.inv_id, exc)
        except Exception as exc:  # recorded as an infrastructure failure, then re-logged
            log.exception("investigation %s failed", self.inv_id)
            self._fail({"type": type(exc).__name__, "detail": str(exc)[:2000]},
                       "unexpected error during investigation")
        finally:
            shutil.rmtree(self.work, ignore_errors=True)

    # -- stages --------------------------------------------------------------------------------
    def _analyze(self) -> _Context:
        with session_scope(self.d.engine) as s:
            inv = s.get(Investigation, self.inv_id)
            if inv is None or is_terminal(inv.state):
                raise Stopped(f"investigation is {inv.state.value if inv else 'deleted'}")
            if inv.state is not S.ANALYZING_REPORT:
                raise RuntimeError(f"expected ANALYZING_REPORT, found {inv.state.value}")
            row = s.get(BugReport, inv.bug_report_id)
            repo = s.get(Repository, inv.repository_id)
            report = BugReportInput(
                title=row.title, description=row.description,
                expected_behavior=row.expected_behavior, actual_behavior=row.actual_behavior,
                reproduction_steps=row.reproduction_steps, stack_trace=row.stack_trace,
                environment=row.environment,
            )
            facts = analyze_report(report)
            row.missing_fields = facts.missing_fields
            archive_key = repo.storage_ref

        self._advance(S.ANALYZING_REPOSITORY, "report analysed", {
            "missing_fields": facts.missing_fields,
            "expected_behavior_known": facts.expected_behavior_known,
        })

        repo_dir = self.work / "repo"
        extract_archive(self.d.blobs.path(archive_key), repo_dir)
        layout = detect_layout(repo_dir)
        index = index_repo(repo_dir)
        modules = module_map(index, layout.source_roots)
        search_text = " ".join(filter(None, [report.title, report.description,
                                             report.expected_behavior, report.actual_behavior,
                                             report.reproduction_steps]))
        ranked = rank_files(index, search_text, report.stack_trace or "")
        evidence_text, included = build_evidence(repo_dir, index, ranked, modules)
        for rf in ranked[:5]:
            self._evidence("code_location", {"file": rf.path, "score": rf.score,
                                             "reasons": rf.reasons, "symbols": rf.symbols,
                                             "sent_to_model": rf.path in included})

        self._advance(S.GENERATING_TEST, "repository analysed", {
            "layout": layout.layout, "python_files": layout.python_file_count,
            "ranked_files": [r.path for r in ranked[:5]],
            "parse_errors": sorted(index.parse_errors)[:20],
        })
        return _Context(report, render_report(report, facts), facts.expected_behavior_known,
                        repo_dir, tuple(layout.source_roots or ["."]), modules, evidence_text)

    def _generate_execute_verify(self, ctx: _Context) -> None:
        max_attempts = self.d.settings.max_generation_attempts
        feedback = ""
        last_problems: tuple[str, ...] | None = None
        tokens_used = 0
        for number in range(1, max_attempts + 1):
            blocked = self._budget_block(tokens_used)
            if blocked:
                self._save_blocked_attempt(blocked)
                self._fail({"type": "LLMBudgetExceeded", "detail": blocked, "retryable": True},
                           "LLM budget exhausted")
                return
            record = generate_once(self.d.provider, self.d.prompt, number=number,
                                   report_text=ctx.report_text, evidence_text=ctx.evidence_text,
                                   modules=ctx.modules, feedback=feedback)
            tokens_used += _tokens(record.llm_metadata)
            attempt_id = self._save_attempt(record)

            if record.llm_error is not None:
                if isinstance(record.llm_error, LLMRefused):
                    self._complete(Outcome.INCONCLUSIVE, OutcomeReason.MODEL_REFUSED,
                                   "the model declined to write a test")
                else:
                    self._fail({"type": type(record.llm_error).__name__,
                                "detail": str(record.llm_error),
                                "retryable": record.llm_error.retryable}, "LLM provider failure")
                return

            ok = bool(record.validation and record.validation.ok)
            self._advance(S.VALIDATING_TEST, f"attempt {number} validated", {
                "attempt": number, "ok": ok, "errors": list(record.problems()),
                "warnings": record.validation.warnings if record.validation else [],
            })
            if not ok:
                problems = record.problems()
                if number == max_attempts or problems == last_problems:
                    self._complete(Outcome.INCONCLUSIVE, OutcomeReason.GENERATION_EXHAUSTED,
                                   "no valid test after bounded attempts")
                    return
                last_problems = problems
                feedback = rejection_feedback(record)
                self._advance(S.GENERATING_TEST, "regenerating after rejection")
                continue

            contract = to_contract(record.output, record.validation, ctx.expected_behavior_known)
            with session_scope(self.d.engine) as s:
                test = s.query(GeneratedTest).filter_by(attempt_id=attempt_id).one()
                test.contract = contract.model_dump(mode="json")

            self._advance(S.EXECUTING_TEST, f"executing attempt {number}")
            runs, run_ids = self._execute(attempt_id, record.output.test_code, ctx)

            self._advance(S.VERIFYING_RESULT, f"verifying attempt {number}")
            verdict = classify([r.result for r in runs], contract)
            verdict_data = verdict.model_dump(mode="json")
            verdict_data["evidence"] = [redact(e) for e in verdict_data["evidence"]]
            # Link the verdict to the execution results it was derived from (provenance).
            self._evidence("verdict", {"attempt": number, "execution_result_ids": run_ids,
                                       **verdict_data}, execution_id=run_ids[0])

            if verdict.outcome is Outcome.EXECUTION_ERROR:
                self._fail({"type": "SandboxError", "detail": "; ".join(verdict.evidence)},
                           "sandbox did not produce a usable result")
                return
            retry = verdict.reason in _RETRY_AFTER_EXECUTION and number < max_attempts
            problems = (verdict.reason.value, runs[0].result.exception_type or "",
                        _normalise(runs[0].result.message))
            if retry and problems != last_problems:
                last_problems = problems
                feedback = execution_feedback(verdict.reason.value, self._run_detail(runs[0]))
                self._advance(S.GENERATING_TEST, f"regenerating after {verdict.reason.value}")
                continue
            self._complete(verdict.outcome, verdict.reason, _summary(verdict))
            return

    # -- helpers -------------------------------------------------------------------------------
    def _budget_block(self, tokens_used: int) -> str | None:
        """Return why the next LLM call must not happen, or None. Checked before every call."""
        s = self.d.settings
        if tokens_used >= s.llm_token_budget_per_investigation:
            return (f"token budget of {s.llm_token_budget_per_investigation} reached "
                    f"({tokens_used} used)")
        since = datetime.now(UTC) - timedelta(hours=24)
        with session_scope(self.d.engine) as session:
            calls = session.query(Attempt).filter(
                Attempt.created_at >= since, Attempt.status != BLOCKED).count()
        if calls >= s.llm_max_calls_per_day:
            return f"daily limit of {s.llm_max_calls_per_day} LLM calls reached"
        return None

    def _save_blocked_attempt(self, reason: str) -> None:
        """Record a call REDFIRST refused to make, so the budget decision is auditable.

        Blocked attempts never reached the provider: zero tokens is a fact, not an estimate,
        and they are excluded from the daily call count.
        """
        request = LLMRequest(system="", user="", prompt_name=self.d.prompt.name,
                             prompt_version=self.d.prompt.version)
        meta = attempt_metadata(self.d.provider, request, call_status="not_sent",
                                usage={"input_tokens": 0, "output_tokens": 0}, error=reason)
        with session_scope(self.d.engine) as s:
            inv = s.get(Investigation, self.inv_id)
            attempt = service.start_attempt(s, inv, self.d.settings.max_generation_attempts)
            attempt.status = BLOCKED
            attempt.llm_metadata = meta

    def _save_attempt(self, record) -> str:
        with session_scope(self.d.engine) as s:
            inv = s.get(Investigation, self.inv_id)
            attempt = service.start_attempt(s, inv, self.d.settings.max_generation_attempts)
            attempt.llm_metadata = record.llm_metadata
            if record.llm_error is not None:
                attempt.status = "llm_error"
            elif record.output is None:
                attempt.status = "invalid_output"
            else:
                attempt.status = "valid" if record.validation.ok else "rejected"
                s.add(GeneratedTest(
                    attempt_id=attempt.id, code=record.output.test_code,
                    validation_result={
                        **record.validation.model_dump(mode="json"),
                        "strategy": record.output.strategy,
                        "assumptions": record.output.assumptions,
                    },
                ))
            if record.error:
                attempt.llm_metadata = {**(attempt.llm_metadata or {}), "error": record.error}
            return attempt.id

    def _execute(self, attempt_id: str, code: str,
                 ctx: _Context) -> tuple[list[SandboxRun], list[str]]:
        """Run the test; returns the runs and the ids of their persisted ExecutionResults."""
        runs: list[SandboxRun] = []
        run_ids: list[str] = []
        for i in range(self.d.settings.reproduction_runs):
            run = self.d.executor(ExecRequest(
                repo_dir=ctx.repo_dir, test_code=code,
                work_dir=self.work / f"run-{attempt_id[:8]}-{i}", source_roots=ctx.source_roots,
            ))
            runs.append(run)
            run_ids.append(self._save_run(attempt_id, i, run))
            if not _worth_repeating(run.result):
                break  # repeating a setup failure or crash adds no evidence
        return runs, run_ids

    def _save_run(self, attempt_id: str, index: int, run: SandboxRun) -> str:
        # Everything persisted or shown later is redacted first; raw output is never stored.
        stdout, stderr = redact(run.stdout), redact(run.stderr)
        stdout_ref = self.d.blobs.put_bytes(stdout.encode()) if stdout else None
        stderr_ref = self.d.blobs.put_bytes(stderr.encode()) if stderr else None
        parsed = run.result.model_dump(mode="json")
        parsed["message"] = redact(parsed["message"])
        parsed["integrity_errors"] = [redact(e) for e in parsed["integrity_errors"]]
        with session_scope(self.d.engine) as s:
            row = ExecutionResult(
                attempt_id=attempt_id, run_index=index, exit_code=run.exit_code,
                duration_ms=run.duration_ms, timed_out=run.result.timed_out,
                oom_killed=run.result.oom_killed, main_status=run.result.main_status,
                stdout_ref=stdout_ref, stderr_ref=stderr_ref,
                stdout_excerpt=stdout[-_EXCERPT:],
                parsed={**parsed, "output_truncated": run.output_truncated},
            )
            s.add(row)
            s.flush()
            s.query(Attempt).filter_by(id=attempt_id).update({"status": "executed"})
            return row.id

    @staticmethod
    def _run_detail(run: SandboxRun) -> str:
        """Feedback for the model: redacted, so secrets printed by repo code never reach it."""
        r = run.result
        head = f"{r.exception_type or ''}: {r.message}".strip(": ")
        return redact(f"{head}\n{run.stdout[-1000:]}")


def _tokens(metadata: dict[str, Any] | None) -> int:
    """Tokens the provider reported for an attempt; unknown usage counts as nothing reported."""
    usage = (metadata or {}).get("usage") or {}
    return int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))


def _worth_repeating(r: RunResult) -> bool:
    if r.runner_crashed or r.collection_error or r.integrity_errors:
        return False  # repeating a crash, setup failure or untrusted report adds no evidence
    if not r.report_parsed and not (r.timed_out or r.oom_killed):
        return False
    return r.main_phase not in (TestPhase.COLLECTION, TestPhase.SETUP)


_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+|/[^\s'\"]+")


def _normalise(message: str) -> str:
    """Strip run-specific paths so the same failure in two attempts compares equal."""
    return _PATH.sub("<path>", message)[:300]


def _summary(verdict: Verdict) -> str:
    return f"{verdict.outcome.value} ({verdict.reason.value})"
