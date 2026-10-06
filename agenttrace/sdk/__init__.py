from agenttrace.security import Redactor, Secret
from agenttrace.storage import SQLiteStorage
from agenttrace.tracing import DecisionTrace


class AgentTrace:
    def __init__(self, db=".agenttrace/traces.sqlite3", redact=(), storage=None):
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
