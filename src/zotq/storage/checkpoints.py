"""Checkpoint persistence for index sync state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class CheckpointStore:
    """Simple JSON checkpoint store."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return {}

    def write(self, *, last_sync_at: datetime) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_sync_at": last_sync_at.isoformat(),
        }
        self._path.write_text(json.dumps(payload, indent=2))
