from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from tracefi.schema import redactor
from tracefi.security import Secret
from tracefi.storage import DEFAULT_DB, SQLiteStorage
from tracefi.tracing import DecisionTrace, TraceSink


class Storage(TraceSink, Protocol):
    def get(self, trace_id: str = "latest", verify: bool = True) -> dict[str, Any]: ...

    def list(self, limit: int = 50) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class TraceFi:
    def __init__(
        self,
        db: str | Path = DEFAULT_DB,
        redact: Iterable[str] = (),
        storage: Storage | None = None,
    ) -> None:
        self.redactor = redactor(redact)
        self.storage: Storage = storage if storage is not None else SQLiteStorage(db)

    def decision(self, agent: str, version: str = "unknown", **kwargs: Any) -> DecisionTrace:
        return DecisionTrace(self.storage, self.redactor, agent, version, **kwargs)

    @staticmethod
    def secret(value: Any) -> Secret:
        """Wrap sensitive values anywhere in a captured payload."""
        return Secret(value)

    def close(self) -> None:
        self.storage.close()

    def __enter__(self) -> TraceFi:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
