"""Checkpoint persistence for index sync state."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class CheckpointStore:
    """Simple JSON checkpoint store."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, object]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return {}

    def _write_payload(self, payload: dict[str, object]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2))

    def write(
        self,
        *,
        last_sync_at: datetime,
        clear_ingest: bool = True,
    ) -> None:
        payload = self.read()
        payload["last_sync_at"] = last_sync_at.isoformat()
        if clear_ingest:
            payload.pop("ingest", None)
        self._write_payload(payload)

    def ingest_state(self) -> dict[str, object] | None:
        payload = self.read()
        ingest = payload.get("ingest")
        if isinstance(ingest, dict):
            return ingest
        return None

    def write_ingest(
        self,
        *,
        mode: str,
        total: int,
        done: int,
        remaining_keys: list[str],
    ) -> None:
        payload = self.read()
        payload["ingest"] = {
            "mode": mode,
            "total": max(0, int(total)),
            "done": max(0, int(done)),
            "remaining_keys": [str(key) for key in remaining_keys if key],
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        self._write_payload(payload)

    def clear_ingest(self) -> None:
        payload = self.read()
        if "ingest" in payload:
            payload.pop("ingest", None)
            self._write_payload(payload)
