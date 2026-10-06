from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from tracefi.security import Redactor, Secret
from tracefi.storage import SQLiteStorage
from tracefi.tracing import DecisionTrace


class TraceFi:
    def __init__(
        self,
        db: str | Path = ".tracefi/traces.sqlite3",
        redact: Iterable[str] = (),
        storage: Any = None,
    ) -> None:
        self.redactor = Redactor(redact)
        self.storage = storage if storage is not None else SQLiteStorage(db)

    def decision(self, agent: str, version: str = "unknown", **kwargs: Any) -> DecisionTrace:
        return DecisionTrace(self, agent, version, **kwargs)

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
