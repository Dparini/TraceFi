"""Private, non-overwriting exports; filesystem parent directories are trusted."""

import os
import tempfile
from pathlib import Path


def write_export(path: str | Path, value: str) -> None:
    """Publish a complete UTF-8 file atomically, refusing existing names/symlinks."""
    destination = Path(path)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".tracefi-", delete=False
        ) as stream:
            temporary = stream.name
            stream.write(value.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        # link is an atomic create-if-absent, including when the destination is a symlink.
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            os.unlink(temporary)
