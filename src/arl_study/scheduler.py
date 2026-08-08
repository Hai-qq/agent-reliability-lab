"""Persistent deterministic study scheduler with fail-closed resume semantics."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from arl.core.types import canonical_json, digest_value

STATE_SCHEMA_VERSION = 1
_SAFE_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9._-]{0,159}")
JobStatus = Literal["pending", "running", "completed"]
StudyStatus = Literal["ready", "running", "interrupted", "complete"]


class StudyStateError(RuntimeError):
    """Raised when persisted study state cannot be trusted or resumed safely."""


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, value: Any, *, refuse_overwrite: bool = False) -> None:
    if refuse_overwrite and path.exists():
        raise FileExistsError(f"Refusing to overwrite JSON artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _validate_identifier(value: str, label: str) -> None:
    if not _SAFE_IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must match {_SAFE_IDENTIFIER.pattern!r}: {value!r}")


@dataclass(frozen=True)
class StudyJob:
    job_id: str
    payload_json: str

    def __post_init__(self) -> None:
        _validate_identifier(self.job_id, "job_id")
        payload = json.loads(self.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("Study job payload must be a JSON object")
        if canonical_json(payload) != self.payload_json:
            raise ValueError("Study job payload must use canonical JSON")

    @classmethod
    def from_payload(cls, job_id: str, payload: dict[str, Any]) -> StudyJob:
        return cls(job_id=job_id, payload_json=canonical_json(payload))

    def payload(self) -> dict[str, Any]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):  # pragma: no cover - guarded by construction
            raise StudyStateError("Persisted study payload is not an object")
        return value

    def as_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "payload": self.payload()}


@dataclass(frozen=True)
class StudyManifest:
    study_id: str
    experiment_version: str
    jobs: tuple[StudyJob, ...]

    def __post_init__(self) -> None:
        _validate_identifier(self.study_id, "study_id")
        if not self.experiment_version:
            raise ValueError("experiment_version is required")
        if not self.jobs:
            raise ValueError("Study manifest requires at least one job")
        identifiers = [job.job_id for job in self.jobs]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Study manifest job IDs must be unique")

    def as_dict(self) -> dict[str, Any]:
        return {
            "study_id": self.study_id,
            "experiment_version": self.experiment_version,
            "jobs": [job.as_dict() for job in self.jobs],
        }

    @property
    def sha256(self) -> str:
        return digest_value(self.as_dict())


@dataclass(frozen=True)
class StudyRunReport:
    study_id: str
    status: StudyStatus
    completed_count: int
    pending_count: int
    total_count: int
    new_jobs_completed: int
    resume_used: bool
    preexisting_completed_count: int
    preexisting_results_sha256_before: str | None
    preexisting_results_sha256_after: str | None
    preexisting_results_preserved: bool | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


JobExecutor = Callable[[StudyJob, Path], dict[str, Any]]


class StudyScheduler:
    """Run a fixed manifest sequentially and persist progress after every transition."""

    def __init__(
        self,
        workspace: Path,
        manifest: StudyManifest,
        state: dict[str, Any],
        *,
        resume_used: bool,
        preexisting_ids: tuple[str, ...] = (),
        preexisting_digest: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.manifest = manifest
        self.state_path = workspace / "study-state.json"
        self._state = state
        self._resume_used = resume_used
        self._preexisting_ids = preexisting_ids
        self._preexisting_digest = preexisting_digest
        self._jobs_by_id = {job.job_id: job for job in manifest.jobs}

    @classmethod
    def create(cls, workspace: Path, manifest: StudyManifest) -> StudyScheduler:
        if workspace.exists():
            raise FileExistsError(f"Refusing to reuse study workspace: {workspace}")
        workspace.mkdir(parents=True)
        for directory in ("attempts", "results", "traces"):
            (workspace / directory).mkdir()
        jobs = {
            job.job_id: {
                "status": "pending",
                "attempt_count": 0,
                "result_file": f"results/{job.job_id}.json",
                "trace_file": f"traces/{job.job_id}.jsonl",
                "result_sha256": None,
                "trace_sha256": None,
            }
            for job in manifest.jobs
        }
        state: dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "study_id": manifest.study_id,
            "status": "ready",
            "manifest": manifest.as_dict(),
            "manifest_sha256": manifest.sha256,
            "jobs": jobs,
            "history": [],
        }
        scheduler = cls(workspace, manifest, state, resume_used=False)
        scheduler._append_history("study_created")
        scheduler._persist()
        return scheduler

    @classmethod
    def resume(cls, workspace: Path, manifest: StudyManifest) -> StudyScheduler:
        state_path = workspace / "study-state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"Study state does not exist: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise StudyStateError("Study state must be a JSON object")
        scheduler = cls(workspace, manifest, state, resume_used=True)
        scheduler._validate_state()
        if scheduler._state["status"] == "complete":
            raise StudyStateError("Study is already complete")
        scheduler._recover_running_jobs()
        preexisting_ids = tuple(scheduler.completed_job_ids())
        preexisting_digest = scheduler._completed_digest(preexisting_ids)
        scheduler._preexisting_ids = preexisting_ids
        scheduler._preexisting_digest = preexisting_digest
        scheduler._append_history(
            "study_resume_started",
            preexisting_completed_count=len(preexisting_ids),
            preexisting_results_sha256=preexisting_digest,
        )
        scheduler._persist()
        return scheduler

    @property
    def state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    def _counts(self) -> tuple[int, int]:
        completed = sum(entry["status"] == "completed" for entry in self._state["jobs"].values())
        return completed, len(self.manifest.jobs) - completed

    def _append_history(self, event_type: str, **details: Any) -> None:
        completed, pending = self._counts()
        self._state["history"].append(
            {
                "sequence": len(self._state["history"]) + 1,
                "event_type": event_type,
                "completed_count": completed,
                "pending_count": pending,
                **details,
            }
        )

    def _persist(self) -> None:
        write_json_atomic(self.state_path, self._state)

    def _entry_paths(self, job_id: str) -> tuple[Path, Path]:
        entry = self._state["jobs"][job_id]
        return self.workspace / entry["result_file"], self.workspace / entry["trace_file"]

    def _attempt_path(self, job_id: str, attempt_count: int) -> Path:
        return self.workspace / "attempts" / f"{job_id}.attempt-{attempt_count}.jsonl"

    def _validate_completed_artifacts(self, job_id: str) -> None:
        entry = self._state["jobs"][job_id]
        result_path, trace_path = self._entry_paths(job_id)
        if not result_path.is_file() or not trace_path.is_file():
            raise StudyStateError(f"Completed job is missing artifacts: {job_id}")
        result_sha = file_sha256(result_path)
        trace_sha = file_sha256(trace_path)
        if result_sha != entry["result_sha256"] or trace_sha != entry["trace_sha256"]:
            raise StudyStateError(f"Completed job artifact hash mismatch: {job_id}")
        record = self._read_result_record(job_id, result_path)
        if record.get("trace_sha256") != trace_sha:
            raise StudyStateError(f"Completed job trace link is invalid: {job_id}")

    def _read_result_record(self, job_id: str, result_path: Path) -> dict[str, Any]:
        try:
            record = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise StudyStateError(f"Job result record is unreadable: {job_id}") from error
        expected_keys = {"job_id", "payload_sha256", "result", "trace_sha256"}
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise StudyStateError(f"Job result record has invalid shape: {job_id}")
        if record["job_id"] != job_id:
            raise StudyStateError(f"Job result record has wrong ID: {job_id}")
        if record["payload_sha256"] != digest_value(self._jobs_by_id[job_id].payload()):
            raise StudyStateError(f"Job result payload link is invalid: {job_id}")
        if not isinstance(record["result"], dict):
            raise StudyStateError(f"Job result payload is invalid: {job_id}")
        if not isinstance(record["trace_sha256"], str):
            raise StudyStateError(f"Job result trace digest is invalid: {job_id}")
        return record

    def _validate_state(self) -> None:
        if self._state.get("schema_version") != STATE_SCHEMA_VERSION:
            raise StudyStateError("Study state schema version mismatch")
        if self._state.get("study_id") != self.manifest.study_id:
            raise StudyStateError("Study ID mismatch")
        if self._state.get("manifest") != self.manifest.as_dict():
            raise StudyStateError("Study manifest does not match persisted state")
        if self._state.get("manifest_sha256") != self.manifest.sha256:
            raise StudyStateError("Study manifest digest mismatch")
        if self._state.get("status") not in {"ready", "running", "interrupted", "complete"}:
            raise StudyStateError("Study status is invalid")
        jobs = self._state.get("jobs")
        history = self._state.get("history")
        if not isinstance(jobs, dict) or not isinstance(history, list):
            raise StudyStateError("Study jobs or history has invalid shape")
        expected_ids = [job.job_id for job in self.manifest.jobs]
        if set(jobs) != set(expected_ids):
            raise StudyStateError("Study state job set does not match manifest")
        for job_id in expected_ids:
            entry = jobs[job_id]
            if not isinstance(entry, dict) or entry.get("status") not in {
                "pending",
                "running",
                "completed",
            }:
                raise StudyStateError(f"Study job status is invalid: {job_id}")
            if not isinstance(entry.get("attempt_count"), int) or entry["attempt_count"] < 0:
                raise StudyStateError(f"Study job attempt count is invalid: {job_id}")
            if entry.get("result_file") != f"results/{job_id}.json":
                raise StudyStateError(f"Study job result path is invalid: {job_id}")
            if entry.get("trace_file") != f"traces/{job_id}.jsonl":
                raise StudyStateError(f"Study job trace path is invalid: {job_id}")
            if entry["status"] == "completed":
                if entry["attempt_count"] < 1:
                    raise StudyStateError(f"Completed job has no attempt: {job_id}")
                if not all(
                    isinstance(entry.get(key), str) for key in ("result_sha256", "trace_sha256")
                ):
                    raise StudyStateError(f"Completed job digests are invalid: {job_id}")
                self._validate_completed_artifacts(job_id)
            else:
                if entry.get("result_sha256") is not None or entry.get("trace_sha256") is not None:
                    raise StudyStateError(f"Incomplete job has final digests: {job_id}")
                if entry["status"] == "running" and entry["attempt_count"] < 1:
                    raise StudyStateError(f"Running job has no attempt: {job_id}")
        if self._state["status"] == "complete" and any(
            entry["status"] != "completed" for entry in jobs.values()
        ):
            raise StudyStateError("Complete study contains incomplete jobs")

    def _complete_from_record(self, job_id: str, result_path: Path, trace_path: Path) -> None:
        entry = self._state["jobs"][job_id]
        record = self._read_result_record(job_id, result_path)
        trace_sha = file_sha256(trace_path)
        if record.get("trace_sha256") != trace_sha:
            raise StudyStateError(f"Cannot reconcile trace hash mismatch: {job_id}")
        entry.update(
            {
                "status": "completed",
                "result_sha256": file_sha256(result_path),
                "trace_sha256": trace_sha,
            }
        )
        self._append_history(
            "job_reconciled",
            job_id=job_id,
            attempt_count=entry["attempt_count"],
        )

    def _recover_running_jobs(self) -> None:
        changed = False
        for job in self.manifest.jobs:
            entry = self._state["jobs"][job.job_id]
            if entry["status"] != "running":
                continue
            result_path, trace_path = self._entry_paths(job.job_id)
            attempt_path = self._attempt_path(job.job_id, entry["attempt_count"])
            if result_path.is_file() and trace_path.is_file():
                self._complete_from_record(job.job_id, result_path, trace_path)
            elif result_path.is_file() and not trace_path.exists() and attempt_path.is_file():
                record = self._read_result_record(job.job_id, result_path)
                if record["trace_sha256"] != file_sha256(attempt_path):
                    raise StudyStateError(
                        f"Cannot reconcile in-flight trace hash mismatch: {job.job_id}"
                    )
                attempt_path.rename(trace_path)
                self._complete_from_record(job.job_id, result_path, trace_path)
            elif not result_path.exists() and not trace_path.exists():
                entry["status"] = "pending"
                self._append_history(
                    "job_requeued",
                    job_id=job.job_id,
                    abandoned_attempt=entry["attempt_count"],
                )
            else:
                raise StudyStateError(f"Cannot safely reconcile running job: {job.job_id}")
            changed = True
        if changed:
            self._state["status"] = "interrupted"
            self._persist()

    def completed_job_ids(self) -> list[str]:
        return [
            job.job_id
            for job in self.manifest.jobs
            if self._state["jobs"][job.job_id]["status"] == "completed"
        ]

    def _completed_digest(self, job_ids: tuple[str, ...] | list[str]) -> str:
        return digest_value(
            [
                {
                    "job_id": job_id,
                    "result_sha256": self._state["jobs"][job_id]["result_sha256"],
                    "trace_sha256": self._state["jobs"][job_id]["trace_sha256"],
                }
                for job_id in job_ids
            ]
        )

    def completed_results(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for job_id in self.completed_job_ids():
            result_path, _ = self._entry_paths(job_id)
            record = json.loads(result_path.read_text(encoding="utf-8"))
            result = record.get("result")
            if not isinstance(result, dict):
                raise StudyStateError(f"Completed result payload is invalid: {job_id}")
            results.append(result)
        return results

    def _report(
        self,
        *,
        new_jobs_completed: int,
        digest_after: str | None,
    ) -> StudyRunReport:
        completed, pending = self._counts()
        preserved = self._preexisting_digest == digest_after if self._resume_used else None
        return StudyRunReport(
            study_id=self.manifest.study_id,
            status=self._state["status"],
            completed_count=completed,
            pending_count=pending,
            total_count=len(self.manifest.jobs),
            new_jobs_completed=new_jobs_completed,
            resume_used=self._resume_used,
            preexisting_completed_count=len(self._preexisting_ids),
            preexisting_results_sha256_before=self._preexisting_digest,
            preexisting_results_sha256_after=digest_after,
            preexisting_results_preserved=preserved,
        )

    def run(
        self,
        execute_job: JobExecutor,
        *,
        max_new_jobs: int | None = None,
    ) -> StudyRunReport:
        if max_new_jobs is not None and max_new_jobs < 1:
            raise ValueError("max_new_jobs must be positive")
        if self._state["status"] == "complete":
            raise StudyStateError("Study is already complete")
        self._state["status"] = "running"
        self._persist()
        new_jobs = 0
        for job in self.manifest.jobs:
            entry = self._state["jobs"][job.job_id]
            if entry["status"] == "completed":
                continue
            if entry["status"] != "pending":
                raise StudyStateError(f"Job is not schedulable: {job.job_id}")
            result_path, trace_path = self._entry_paths(job.job_id)
            if result_path.exists() or trace_path.exists():
                raise StudyStateError(f"Pending job already has final artifacts: {job.job_id}")
            entry["status"] = "running"
            entry["attempt_count"] += 1
            attempt_path = self._attempt_path(job.job_id, entry["attempt_count"])
            if attempt_path.exists():
                raise StudyStateError(f"Attempt trace already exists: {attempt_path}")
            self._append_history(
                "job_started",
                job_id=job.job_id,
                attempt_count=entry["attempt_count"],
            )
            self._persist()
            try:
                result = execute_job(job, attempt_path)
                if not isinstance(result, dict):
                    raise TypeError("Job executor must return a dictionary")
                if not attempt_path.is_file():
                    raise StudyStateError(f"Job executor did not write a trace: {job.job_id}")
                trace_sha = file_sha256(attempt_path)
                declared_trace_sha = result.get("trace_sha256")
                if declared_trace_sha is not None and declared_trace_sha != trace_sha:
                    raise StudyStateError(f"Job result trace hash mismatch: {job.job_id}")
                record = {
                    "job_id": job.job_id,
                    "payload_sha256": digest_value(job.payload()),
                    "result": result,
                    "trace_sha256": trace_sha,
                }
                write_json_atomic(result_path, record, refuse_overwrite=True)
                if trace_path.exists():
                    raise FileExistsError(f"Refusing to overwrite trace: {trace_path}")
                attempt_path.rename(trace_path)
                entry.update(
                    {
                        "status": "completed",
                        "result_sha256": file_sha256(result_path),
                        "trace_sha256": trace_sha,
                    }
                )
                new_jobs += 1
                self._append_history(
                    "job_completed",
                    job_id=job.job_id,
                    attempt_count=entry["attempt_count"],
                    result_sha256=entry["result_sha256"],
                    trace_sha256=trace_sha,
                )
                self._persist()
            except Exception as error:
                self._state["status"] = "interrupted"
                self._append_history(
                    "job_execution_failed",
                    job_id=job.job_id,
                    attempt_count=entry["attempt_count"],
                    error_type=type(error).__name__,
                )
                self._persist()
                raise

            completed, pending = self._counts()
            if max_new_jobs is not None and new_jobs >= max_new_jobs and pending:
                self._state["status"] = "interrupted"
                self._append_history(
                    "study_intentionally_stopped",
                    new_jobs_completed=new_jobs,
                )
                self._persist()
                return self._report(new_jobs_completed=new_jobs, digest_after=None)

        digest_after: str | None = None
        if self._resume_used:
            digest_after = self._completed_digest(self._preexisting_ids)
            preserved = digest_after == self._preexisting_digest
            self._append_history(
                "study_resume_completed",
                preexisting_completed_count=len(self._preexisting_ids),
                preexisting_results_sha256_before=self._preexisting_digest,
                preexisting_results_sha256_after=digest_after,
                preserved=preserved,
            )
            if not preserved:
                raise StudyStateError("Resume changed preexisting completed results")
        self._state["status"] = "complete"
        self._append_history("study_completed")
        self._persist()
        return self._report(new_jobs_completed=new_jobs, digest_after=digest_after)
