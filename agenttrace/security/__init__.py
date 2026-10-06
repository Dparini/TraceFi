"""Redact before serialization, hashing, persistence and export."""
from collections.abc import Mapping

REDACTED = "[REDACTED]"
DEFAULT_KEYS = {"api_key", "private_key", "authorization", "password", "secret", "access_token", "refresh_token"}


class Secret:
    """Explicitly mark a value sensitive; its repr never reveals the value."""
    def __init__(self, value):
        self._value = value

    def __repr__(self):
        return REDACTED

    def reveal(self):
        return self._value


def _key(value):
    return value.casefold().replace("-", "").replace("_", "")


class Redactor:
    def __init__(self, keys=()):
        self.keys = {_key(key) for key in DEFAULT_KEYS | set(keys)}

    def __call__(self, value):
        if isinstance(value, Secret):
            return REDACTED
        if isinstance(value, Mapping):
            return {key: REDACTED if isinstance(key, str) and _key(key) in self.keys else self(part)
                    for key, part in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(part) for part in value]
        return value
