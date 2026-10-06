from tracefi.security import Redactor, Secret
from tracefi.storage import SQLiteStorage
from tracefi.tracing import DecisionTrace


class TraceFi:
    def __init__(self, db=".tracefi/traces.sqlite3", redact=(), storage=None):
        self.redactor = Redactor(redact)
        self.storage = storage if storage is not None else SQLiteStorage(db)

    def decision(self, agent, version="unknown", **kwargs):
        return DecisionTrace(self, agent, version, **kwargs)

    @staticmethod
    def secret(value):
        """Wrap sensitive values anywhere in a captured payload."""
        return Secret(value)

    def close(self):
        self.storage.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
