"""Deterministic parallel study scheduler with persistent worker leases."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from arl.core.types import digest_value
from arl_study.scheduler import (
    StudyJob,
    StudyManifest,
    file_sha256,
    write_json_atomic,
)

PARALLEL_STATE_SCHEMA_VERSION = 1
ParallelStudyStatus = Literal["ready", "running", "interrupted", "complete"]


class ParallelStudyStateError(RuntimeError):
    """Raised when lease state or persisted artifacts cannot be trusted."""


class StaleLeaseError(ParallelStudyStateError):
    """Raised when a worker tries to commit an expired or replaced lease."""


class WorkerAttemptsExhausted(ParallelStudyStateError):
    """Raised when a job repeatedly fails beyond the configured attempt bound."""


@dataclass(frozen=True)
class JobLease:
    job_id: str
    worker_id: str
    epoch: int
    token: str
    expires_at_tick: int
    attempt_path: Path


@dataclass(frozen=True)
class ParallelRunReport:
    study_id: str
    status: ParallelStudyStatus
    completed_count: int
    pending_count: int
    leased_count: int
    total_count: int
    new_jobs_completed: int
    resume_used: bool
    preexisting_completed_count: int
    preexisting_results_sha256_before: str | None
    preexisting_results_sha256_after: str | None
    preexisting_results_preserved: bool | None
    lease_acquisition_count: int
    lease_expiration_count: int
    stale_commit_rejection_count: int
    worker_failure_count: int
    heartbeat_count: int
    max_leased_count: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


ParallelJobExecutor = Callable[[StudyJob, Path], dict[str, Any]]


def _cleared_lease() -> dict[str, None]:
    return {
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at_tick": None,
    }


class ParallelStudyScheduler:
    """Execute fixed jobs concurrently while serializing deterministic commits."""

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
        self.state_path = workspace / "parallel-study-state.json"
        self._state = state
        self._resume_used = resume_used
        self._preexisting_ids = preexisting_ids
        self._preexisting_digest = preexisting_digest
        self._jobs_by_id = {job.job_id: job for job in manifest.jobs}

    @classmethod
    def create(
        cls,
        workspace: Path,
        manifest: StudyManifest,
        *,
        worker_count: int = 4,
        lease_duration_ticks: int = 100,
    ) -> ParallelStudyScheduler:
        if workspace.exists():
            raise FileExistsError(f"Refusing to reuse parallel study workspace: {workspace}")
        if worker_count < 2:
            raise ValueError("Parallel study requires at least two workers")
        if lease_duration_ticks < worker_count * 4:
            raise ValueError("lease_duration_ticks is too small for a deterministic wave")
        workspace.mkdir(parents=True)
        for directory in ("attempts", "results", "traces"):
            (workspace / directory).mkdir()
        jobs = {
            job.job_id: {
                "status": "pending",
                "attempt_count": 0,
                "lease_epoch": 0,
                **_cleared_lease(),
                "committed_worker": None,
                "committed_epoch": None,
                "commit_count": 0,
                "result_file": f"results/{job.job_id}.json",
                "trace_file": f"traces/{job.job_id}.jsonl",
                "result_sha256": None,
                "trace_sha256": None,
            }
            for job in manifest.jobs
        }
        state: dict[str, Any] = {
            "schema_version": PARALLEL_STATE_SCHEMA_VERSION,
            "study_id": manifest.study_id,
            "status": "ready",
            "manifest": manifest.as_dict(),
            "manifest_sha256": manifest.sha256,
            "worker_ids": [f"worker-{index}" for index in range(worker_count)],
            "lease_duration_ticks": lease_duration_ticks,
            "logical_tick": 0,
            "jobs": jobs,
            "history": [],
        }
        scheduler = cls(workspace, manifest, state, resume_used=False)
        scheduler._append_history("parallel_study_created")
        scheduler._persist()
        return scheduler

    @classmethod
    def resume(
        cls,
        workspace: Path,
        manifest: StudyManifest,
        *,
        worker_count: int,
        lease_duration_ticks: int,
    ) -> ParallelStudyScheduler:
        state_path = workspace / "parallel-study-state.json"
        if not state_path.is_file():
            raise FileNotFoundError(f"Parallel study state does not exist: {state_path}")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ParallelStudyStateError("Parallel study state must be a JSON object")
        scheduler = cls(workspace, manifest, state, resume_used=True)
        scheduler._validate_state(
            expected_worker_count=worker_count,
            expected_lease_duration=lease_duration_ticks,
        )
        if scheduler._state["status"] == "complete":
            raise ParallelStudyStateError("Parallel study is already complete")
        scheduler._recover_committed_leases()
        preexisting_ids = tuple(scheduler.completed_job_ids())
        preexisting_digest = scheduler._completed_digest(preexisting_ids)
        scheduler._preexisting_ids = preexisting_ids
        scheduler._preexisting_digest = preexisting_digest
        scheduler._append_history(
            "parallel_study_resume_started",
            preexisting_completed_count=len(preexisting_ids),
            preexisting_results_sha256=preexisting_digest,
        )
        scheduler._persist()
        return scheduler

    @property
    def state(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    @property
    def worker_count(self) -> int:
        return len(self._state["worker_ids"])

    @property
    def lease_duration_ticks(self) -> int:
        return self._state["lease_duration_ticks"]

    def _counts(self) -> tuple[int, int, int]:
        statuses = [entry["status"] for entry in self._state["jobs"].values()]
        completed = statuses.count("completed")
        leased = statuses.count("leased")
        pending = len(statuses) - completed - leased
        return completed, pending, leased

    def _append_history(self, event_type: str, **details: Any) -> None:
        completed, pending, leased = self._counts()
        self._state["history"].append(
            {
                "sequence": len(self._state["history"]) + 1,
                "logical_tick": self._state["logical_tick"],
                "event_type": event_type,
                "completed_count": completed,
                "pending_count": pending,
                "leased_count": leased,
                **details,
            }
        )

    def _persist(self) -> None:
        write_json_atomic(self.state_path, self._state)

    def _tick(self, amount: int = 1) -> int:
        self._state["logical_tick"] += amount
        return self._state["logical_tick"]

    def _entry_paths(self, job_id: str) -> tuple[Path, Path]:
        entry = self._state["jobs"][job_id]
        return self.workspace / entry["result_file"], self.workspace / entry["trace_file"]

    def _attempt_path(self, job_id: str, epoch: int) -> Path:
        return self.workspace / "attempts" / f"{job_id}.lease-{epoch}.jsonl"

    def _lease_token(self, job_id: str, worker_id: str, epoch: int) -> str:
        return digest_value(
            {
                "manifest_sha256": self.manifest.sha256,
                "job_id": job_id,
                "worker_id": worker_id,
                "epoch": epoch,
            }
        )

    def _read_result_record(self, job_id: str, result_path: Path) -> dict[str, Any]:
        try:
            record = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ParallelStudyStateError(
                f"Parallel result record is unreadable: {job_id}"
            ) from error
        expected_keys = {
            "job_id",
            "payload_sha256",
            "worker_id",
            "lease_epoch",
            "lease_token",
            "result",
            "trace_sha256",
        }
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise ParallelStudyStateError(f"Parallel result record has invalid shape: {job_id}")
        if record["job_id"] != job_id:
            raise ParallelStudyStateError(f"Parallel result record has wrong ID: {job_id}")
        if record["payload_sha256"] != digest_value(self._jobs_by_id[job_id].payload()):
            raise ParallelStudyStateError(f"Parallel result payload link is invalid: {job_id}")
        if not isinstance(record["result"], dict) or not isinstance(record["trace_sha256"], str):
            raise ParallelStudyStateError(f"Parallel result payload is invalid: {job_id}")
        return record

    def _validate_record_lease(self, job_id: str, record: dict[str, Any]) -> None:
        entry = self._state["jobs"][job_id]
        if (
            record["worker_id"] != entry["lease_owner"]
            or record["lease_epoch"] != entry["lease_epoch"]
            or record["lease_token"] != entry["lease_token"]
        ):
            raise ParallelStudyStateError(f"Parallel result lease link is invalid: {job_id}")

    def _validate_completed_artifacts(self, job_id: str) -> None:
        entry = self._state["jobs"][job_id]
        result_path, trace_path = self._entry_paths(job_id)
        if not result_path.is_file() or not trace_path.is_file():
            raise ParallelStudyStateError(f"Completed parallel job is missing artifacts: {job_id}")
        if file_sha256(result_path) != entry["result_sha256"]:
            raise ParallelStudyStateError(f"Parallel result hash mismatch: {job_id}")
        trace_sha = file_sha256(trace_path)
        if trace_sha != entry["trace_sha256"]:
            raise ParallelStudyStateError(f"Parallel trace hash mismatch: {job_id}")
        record = self._read_result_record(job_id, result_path)
        if (
            record["trace_sha256"] != trace_sha
            or record["worker_id"] != entry["committed_worker"]
            or record["lease_epoch"] != entry["committed_epoch"]
        ):
            raise ParallelStudyStateError(f"Completed parallel artifact link is invalid: {job_id}")

    def _validate_state(self, *, expected_worker_count: int, expected_lease_duration: int) -> None:
        state = self._state
        if state.get("schema_version") != PARALLEL_STATE_SCHEMA_VERSION:
            raise ParallelStudyStateError("Parallel state schema version mismatch")
        if state.get("study_id") != self.manifest.study_id:
            raise ParallelStudyStateError("Parallel study ID mismatch")
        if state.get("manifest") != self.manifest.as_dict():
            raise ParallelStudyStateError("Parallel study manifest mismatch")
        if state.get("manifest_sha256") != self.manifest.sha256:
            raise ParallelStudyStateError("Parallel study manifest digest mismatch")
        expected_workers = [f"worker-{index}" for index in range(expected_worker_count)]
        if state.get("worker_ids") != expected_workers:
            raise ParallelStudyStateError("Parallel worker set mismatch")
        if state.get("lease_duration_ticks") != expected_lease_duration:
            raise ParallelStudyStateError("Parallel lease duration mismatch")
        if state.get("status") not in {"ready", "running", "interrupted", "complete"}:
            raise ParallelStudyStateError("Parallel study status is invalid")
        if not isinstance(state.get("logical_tick"), int) or state["logical_tick"] < 0:
            raise ParallelStudyStateError("Parallel logical tick is invalid")
        jobs = state.get("jobs")
        history = state.get("history")
        if not isinstance(jobs, dict) or not isinstance(history, list):
            raise ParallelStudyStateError("Parallel jobs or history has invalid shape")
        expected_ids = [job.job_id for job in self.manifest.jobs]
        if set(jobs) != set(expected_ids):
            raise ParallelStudyStateError("Parallel job set does not match manifest")
        for job_id in expected_ids:
            entry = jobs[job_id]
            if not isinstance(entry, dict) or entry.get("status") not in {
                "pending",
                "leased",
                "completed",
            }:
                raise ParallelStudyStateError(f"Parallel job status is invalid: {job_id}")
            for key in ("attempt_count", "lease_epoch", "commit_count"):
                if not isinstance(entry.get(key), int) or entry[key] < 0:
                    raise ParallelStudyStateError(f"Parallel job counter is invalid: {job_id}")
            if entry["attempt_count"] != entry["lease_epoch"]:
                raise ParallelStudyStateError(f"Parallel lease epoch is inconsistent: {job_id}")
            if entry.get("result_file") != f"results/{job_id}.json":
                raise ParallelStudyStateError(f"Parallel result path is invalid: {job_id}")
            if entry.get("trace_file") != f"traces/{job_id}.jsonl":
                raise ParallelStudyStateError(f"Parallel trace path is invalid: {job_id}")
            result_path, trace_path = self._entry_paths(job_id)
            if entry["status"] == "completed":
                if entry["commit_count"] != 1 or entry["committed_epoch"] is None:
                    raise ParallelStudyStateError(f"Parallel completed commit is invalid: {job_id}")
                if any(entry[key] is not None for key in _cleared_lease()):
                    raise ParallelStudyStateError(f"Completed job still has a lease: {job_id}")
                self._validate_completed_artifacts(job_id)
            elif entry["status"] == "leased":
                if entry["commit_count"] != 0:
                    raise ParallelStudyStateError(f"Leased job already has a commit: {job_id}")
                if entry["lease_owner"] not in expected_workers:
                    raise ParallelStudyStateError(f"Leased job owner is invalid: {job_id}")
                if not isinstance(entry["lease_token"], str) or not isinstance(
                    entry["lease_expires_at_tick"], int
                ):
                    raise ParallelStudyStateError(f"Leased job metadata is invalid: {job_id}")
                expected_token = self._lease_token(
                    job_id, entry["lease_owner"], entry["lease_epoch"]
                )
                if entry["lease_token"] != expected_token:
                    raise ParallelStudyStateError(f"Leased job token is invalid: {job_id}")
            else:
                if any(entry[key] is not None for key in _cleared_lease()):
                    raise ParallelStudyStateError(f"Pending job has lease metadata: {job_id}")
                if result_path.exists() or trace_path.exists():
                    raise ParallelStudyStateError(f"Pending job has final artifacts: {job_id}")
            if entry["status"] != "completed" and (
                entry["result_sha256"] is not None or entry["trace_sha256"] is not None
            ):
                raise ParallelStudyStateError(f"Incomplete job has final digests: {job_id}")
        if state["status"] == "complete" and any(
            entry["status"] != "completed" for entry in jobs.values()
        ):
            raise ParallelStudyStateError("Complete parallel study contains incomplete jobs")

    def _complete_from_record(
        self,
        job_id: str,
        record: dict[str, Any],
        result_path: Path,
        trace_path: Path,
    ) -> None:
        entry = self._state["jobs"][job_id]
        trace_sha = file_sha256(trace_path)
        if record["trace_sha256"] != trace_sha:
            raise ParallelStudyStateError(f"Cannot reconcile parallel trace hash: {job_id}")
        entry.update(
            {
                "status": "completed",
                **_cleared_lease(),
                "committed_worker": record["worker_id"],
                "committed_epoch": record["lease_epoch"],
                "commit_count": 1,
                "result_sha256": file_sha256(result_path),
                "trace_sha256": trace_sha,
            }
        )
        self._tick()
        self._append_history(
            "lease_commit_reconciled",
            job_id=job_id,
            worker_id=record["worker_id"],
            lease_epoch=record["lease_epoch"],
        )
        self._persist()

    def _recover_committed_leases(self) -> None:
        for job in self.manifest.jobs:
            entry = self._state["jobs"][job.job_id]
            if entry["status"] != "leased":
                continue
            result_path, trace_path = self._entry_paths(job.job_id)
            attempt_path = self._attempt_path(job.job_id, entry["lease_epoch"])
            if result_path.is_file() and trace_path.is_file():
                record = self._read_result_record(job.job_id, result_path)
                self._validate_record_lease(job.job_id, record)
                self._complete_from_record(job.job_id, record, result_path, trace_path)
            elif result_path.is_file() and not trace_path.exists() and attempt_path.is_file():
                record = self._read_result_record(job.job_id, result_path)
                self._validate_record_lease(job.job_id, record)
                if record["trace_sha256"] != file_sha256(attempt_path):
                    raise ParallelStudyStateError(
                        f"Cannot reconcile parallel attempt trace: {job.job_id}"
                    )
                attempt_path.rename(trace_path)
                self._complete_from_record(job.job_id, record, result_path, trace_path)
            elif not result_path.exists() and not trace_path.exists():
                continue
            else:
                raise ParallelStudyStateError(
                    f"Cannot safely reconcile leased parallel job: {job.job_id}"
                )

    def completed_job_ids(self) -> list[str]:
        return [
            job.job_id
            for job in self.manifest.jobs
            if self._state["jobs"][job.job_id]["status"] == "completed"
        ]

    def completed_results(self) -> list[dict[str, Any]]:
        results = []
        for job_id in self.completed_job_ids():
            result_path, _ = self._entry_paths(job_id)
            results.append(self._read_result_record(job_id, result_path)["result"])
        return results

    def _completed_digest(self, job_ids: Iterable[str]) -> str:
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

    def _current_lease(self, lease: JobLease) -> bool:
        entry = self._state["jobs"][lease.job_id]
        return (
            entry["status"] == "leased"
            and entry["lease_owner"] == lease.worker_id
            and entry["lease_epoch"] == lease.epoch
            and entry["lease_token"] == lease.token
        )

    def _require_current_lease(self, lease: JobLease) -> dict[str, Any]:
        if not self._current_lease(lease):
            raise StaleLeaseError(f"Lease is no longer current: {lease.job_id}")
        entry = self._state["jobs"][lease.job_id]
        if self._state["logical_tick"] >= entry["lease_expires_at_tick"]:
            raise StaleLeaseError(f"Lease has expired: {lease.job_id}")
        return entry

    def acquire_pending(self, limit: int) -> tuple[JobLease, ...]:
        if limit < 1 or limit > self.worker_count:
            raise ValueError("Lease batch size must fit the configured worker pool")
        pending = [
            job
            for job in self.manifest.jobs
            if self._state["jobs"][job.job_id]["status"] == "pending"
        ][:limit]
        leases = []
        for index, job in enumerate(pending):
            entry = self._state["jobs"][job.job_id]
            worker_id = self._state["worker_ids"][index]
            epoch = entry["lease_epoch"] + 1
            attempt_path = self._attempt_path(job.job_id, epoch)
            if attempt_path.exists():
                raise ParallelStudyStateError(f"Parallel attempt already exists: {attempt_path}")
            current_tick = self._tick()
            token = self._lease_token(job.job_id, worker_id, epoch)
            expires_at = current_tick + self.lease_duration_ticks
            entry.update(
                {
                    "status": "leased",
                    "attempt_count": epoch,
                    "lease_epoch": epoch,
                    "lease_owner": worker_id,
                    "lease_token": token,
                    "lease_expires_at_tick": expires_at,
                }
            )
            lease = JobLease(
                job_id=job.job_id,
                worker_id=worker_id,
                epoch=epoch,
                token=token,
                expires_at_tick=expires_at,
                attempt_path=attempt_path,
            )
            leases.append(lease)
            self._append_history(
                "lease_acquired",
                job_id=job.job_id,
                worker_id=worker_id,
                lease_epoch=epoch,
                lease_token=token,
                expires_at_tick=expires_at,
            )
            self._persist()
        return tuple(leases)

    def heartbeat(self, lease: JobLease) -> None:
        entry = self._require_current_lease(lease)
        self._tick()
        entry["lease_expires_at_tick"] += self.lease_duration_ticks
        self._append_history(
            "lease_heartbeat",
            job_id=lease.job_id,
            worker_id=lease.worker_id,
            lease_epoch=lease.epoch,
            expires_at_tick=entry["lease_expires_at_tick"],
        )
        self._persist()

    def expire_due_leases(self, target_tick: int) -> tuple[str, ...]:
        if target_tick < self._state["logical_tick"]:
            raise ValueError("Cannot move the logical lease clock backwards")
        self._state["logical_tick"] = target_tick
        expired = []
        for job in self.manifest.jobs:
            entry = self._state["jobs"][job.job_id]
            if entry["status"] != "leased":
                continue
            if entry["lease_expires_at_tick"] > target_tick:
                continue
            owner = entry["lease_owner"]
            epoch = entry["lease_epoch"]
            token = entry["lease_token"]
            entry.update({"status": "pending", **_cleared_lease()})
            expired.append(job.job_id)
            self._append_history(
                "lease_expired",
                job_id=job.job_id,
                worker_id=owner,
                lease_epoch=epoch,
                lease_token=token,
            )
            self._persist()
        return tuple(expired)

    def reclaim_all_leases(self) -> tuple[str, ...]:
        expirations = [
            entry["lease_expires_at_tick"]
            for entry in self._state["jobs"].values()
            if entry["status"] == "leased"
        ]
        if not expirations:
            return ()
        expired = self.expire_due_leases(max(expirations))
        self._state["status"] = "interrupted"
        self._append_history("resume_reclaimed_leases", reclaimed_job_ids=list(expired))
        self._persist()
        return expired

    def force_expire(self, lease: JobLease) -> tuple[str, ...]:
        self._require_current_lease(lease)
        return self.expire_due_leases(lease.expires_at_tick)

    def fail_lease(self, lease: JobLease, error: Exception) -> None:
        entry = self._require_current_lease(lease)
        result_path, trace_path = self._entry_paths(lease.job_id)
        if result_path.exists() or trace_path.exists():
            raise ParallelStudyStateError(
                f"Failed worker unexpectedly produced final artifacts: {lease.job_id}"
            )
        self._tick()
        entry.update({"status": "pending", **_cleared_lease()})
        self._append_history(
            "worker_execution_failed",
            job_id=lease.job_id,
            worker_id=lease.worker_id,
            lease_epoch=lease.epoch,
            error_type=type(error).__name__,
        )
        self._persist()

    def commit_lease(self, lease: JobLease, result: dict[str, Any]) -> None:
        if not isinstance(result, dict):
            raise TypeError("Parallel job executor must return a dictionary")
        try:
            entry = self._require_current_lease(lease)
        except StaleLeaseError:
            self._append_history(
                "stale_commit_rejected",
                job_id=lease.job_id,
                worker_id=lease.worker_id,
                lease_epoch=lease.epoch,
                lease_token=lease.token,
            )
            self._persist()
            raise
        result_path, trace_path = self._entry_paths(lease.job_id)
        if result_path.exists() or trace_path.exists():
            raise ParallelStudyStateError(f"Refusing duplicate final commit: {lease.job_id}")
        if not lease.attempt_path.is_file():
            raise ParallelStudyStateError(f"Parallel executor wrote no trace: {lease.job_id}")
        trace_sha = file_sha256(lease.attempt_path)
        declared_trace_sha = result.get("trace_sha256")
        if declared_trace_sha is not None and declared_trace_sha != trace_sha:
            raise ParallelStudyStateError(f"Parallel result trace hash mismatch: {lease.job_id}")
        record = {
            "job_id": lease.job_id,
            "payload_sha256": digest_value(self._jobs_by_id[lease.job_id].payload()),
            "worker_id": lease.worker_id,
            "lease_epoch": lease.epoch,
            "lease_token": lease.token,
            "result": result,
            "trace_sha256": trace_sha,
        }
        write_json_atomic(result_path, record, refuse_overwrite=True)
        lease.attempt_path.rename(trace_path)
        self._tick()
        entry.update(
            {
                "status": "completed",
                **_cleared_lease(),
                "committed_worker": lease.worker_id,
                "committed_epoch": lease.epoch,
                "commit_count": entry["commit_count"] + 1,
                "result_sha256": file_sha256(result_path),
                "trace_sha256": trace_sha,
            }
        )
        self._append_history(
            "lease_committed",
            job_id=lease.job_id,
            worker_id=lease.worker_id,
            lease_epoch=lease.epoch,
            result_sha256=entry["result_sha256"],
            trace_sha256=trace_sha,
        )
        self._persist()

    def _event_count(self, event_type: str) -> int:
        return sum(item["event_type"] == event_type for item in self._state["history"])

    def _max_leased_count(self) -> int:
        return max((item["leased_count"] for item in self._state["history"]), default=0)

    def _report(
        self,
        *,
        new_jobs_completed: int,
        digest_after: str | None,
    ) -> ParallelRunReport:
        completed, pending, leased = self._counts()
        preserved = self._preexisting_digest == digest_after if self._resume_used else None
        return ParallelRunReport(
            study_id=self.manifest.study_id,
            status=self._state["status"],
            completed_count=completed,
            pending_count=pending,
            leased_count=leased,
            total_count=len(self.manifest.jobs),
            new_jobs_completed=new_jobs_completed,
            resume_used=self._resume_used,
            preexisting_completed_count=len(self._preexisting_ids),
            preexisting_results_sha256_before=self._preexisting_digest,
            preexisting_results_sha256_after=digest_after,
            preexisting_results_preserved=preserved,
            lease_acquisition_count=self._event_count("lease_acquired"),
            lease_expiration_count=self._event_count("lease_expired"),
            stale_commit_rejection_count=self._event_count("stale_commit_rejected"),
            worker_failure_count=self._event_count("worker_execution_failed"),
            heartbeat_count=self._event_count("lease_heartbeat"),
            max_leased_count=self._max_leased_count(),
        )

    def run(
        self,
        execute_job: ParallelJobExecutor,
        *,
        max_new_jobs: int | None = None,
        leave_leases: int = 0,
        expire_once_job_ids: Iterable[str] = (),
        heartbeat_once_job_ids: Iterable[str] = (),
        max_attempts_per_job: int = 3,
    ) -> ParallelRunReport:
        if max_new_jobs is not None and max_new_jobs < 1:
            raise ValueError("max_new_jobs must be positive")
        if leave_leases < 0 or leave_leases > self.worker_count:
            raise ValueError("leave_leases must fit the worker pool")
        if leave_leases and max_new_jobs is None:
            raise ValueError("leave_leases requires max_new_jobs")
        if max_attempts_per_job < 1:
            raise ValueError("max_attempts_per_job must be positive")
        if self._state["status"] == "complete":
            raise ParallelStudyStateError("Parallel study is already complete")
        _, _, leased = self._counts()
        if leased:
            raise ParallelStudyStateError("Active leases must be reclaimed before running")
        known_ids = set(self._jobs_by_id)
        expire_ids = set(expire_once_job_ids)
        heartbeat_ids = set(heartbeat_once_job_ids)
        if not expire_ids <= known_ids or not heartbeat_ids <= known_ids:
            raise ValueError("Fault and heartbeat plans must reference manifest jobs")

        self._state["status"] = "running"
        self._persist()
        new_jobs = 0
        while True:
            _, pending, _ = self._counts()
            if not pending:
                break
            remaining = self.worker_count
            if max_new_jobs is not None:
                remaining = min(remaining, max_new_jobs - new_jobs)
            if remaining < 1:
                break
            leases = self.acquire_pending(min(remaining, pending))
            for lease in leases:
                if lease.job_id in heartbeat_ids and lease.epoch == 1:
                    self.heartbeat(lease)
            with ThreadPoolExecutor(
                max_workers=self.worker_count,
                thread_name_prefix="arl-worker",
            ) as executor:
                futures = [
                    executor.submit(
                        execute_job,
                        self._jobs_by_id[lease.job_id],
                        lease.attempt_path,
                    )
                    for lease in leases
                ]
                outcomes: list[dict[str, Any] | Exception] = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except Exception as error:  # worker failures are study evidence
                        outcomes.append(error)
            for lease, outcome in zip(leases, outcomes, strict=True):
                if isinstance(outcome, Exception):
                    self.fail_lease(lease, outcome)
                    if self._state["jobs"][lease.job_id]["attempt_count"] >= max_attempts_per_job:
                        self._state["status"] = "interrupted"
                        self._append_history(
                            "worker_attempts_exhausted",
                            job_id=lease.job_id,
                            attempt_count=self._state["jobs"][lease.job_id]["attempt_count"],
                        )
                        self._persist()
                        raise WorkerAttemptsExhausted(lease.job_id) from outcome
                    continue
                if lease.job_id in expire_ids and lease.epoch == 1:
                    expired = self.force_expire(lease)
                    if lease.job_id not in expired:
                        raise ParallelStudyStateError(
                            f"Planned lease did not expire: {lease.job_id}"
                        )
                    try:
                        self.commit_lease(lease, outcome)
                    except StaleLeaseError:
                        pass
                    else:  # pragma: no cover - defensive gate
                        raise AssertionError("Expired lease unexpectedly committed")
                    continue
                self.commit_lease(lease, outcome)
                new_jobs += 1

            _, pending, leased = self._counts()
            if max_new_jobs is not None and new_jobs >= max_new_jobs and pending:
                if leased:
                    raise ParallelStudyStateError("Wave ended with unexpected active leases")
                if leave_leases:
                    self.acquire_pending(min(leave_leases, pending))
                self._state["status"] = "interrupted"
                self._append_history(
                    "parallel_study_intentionally_stopped",
                    new_jobs_completed=new_jobs,
                    active_leases=self._counts()[2],
                )
                self._persist()
                return self._report(new_jobs_completed=new_jobs, digest_after=None)

        digest_after: str | None = None
        if self._resume_used:
            digest_after = self._completed_digest(self._preexisting_ids)
            preserved = digest_after == self._preexisting_digest
            self._append_history(
                "parallel_study_resume_completed",
                preexisting_completed_count=len(self._preexisting_ids),
                preexisting_results_sha256_before=self._preexisting_digest,
                preexisting_results_sha256_after=digest_after,
                preserved=preserved,
            )
            if not preserved:
                raise ParallelStudyStateError("Resume changed preexisting parallel results")
        self._state["status"] = "complete"
        self._append_history("parallel_study_completed")
        self._persist()
        return self._report(new_jobs_completed=new_jobs, digest_after=digest_after)


def directory_manifest(paths: Iterable[Path]) -> dict[str, Any]:
    """Return a deterministic filename-to-hash manifest for one artifact class."""
    files = {path.name: file_sha256(path) for path in sorted(paths)}
    payload = json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "algorithm": "sha256(canonical_json({filename: file_sha256}))",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "files": files,
    }
