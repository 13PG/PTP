from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from threading import Lock
from typing import Any


@dataclass
class JobRecord:
    job_id: str
    status: str = "queued"
    progress: int = 0
    stage: str = "queued"
    message: str = "任务已创建，等待开始。"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = Lock()

    def create(self, job_id: str, **fields: Any) -> dict[str, Any]:
        record = JobRecord(job_id=job_id)
        for key, value in fields.items():
            setattr(record, key, value)
        with self._lock:
            self._jobs[job_id] = record
        return self.get(job_id)

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        with self._lock:
            record = self._jobs[job_id]
            for key, value in fields.items():
                setattr(record, key, value)
            record.updated_at = datetime.now().isoformat(timespec="seconds")
            snapshot = deepcopy(record.__dict__)
        return snapshot

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return None
            return deepcopy(record.__dict__)
