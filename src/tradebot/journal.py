"""Append-only, local decisions journal. No secrets or credential fields."""
import json
from datetime import datetime, timezone
from pathlib import Path


def record(path: str, kind: str, details: dict) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    event = {"at_utc": datetime.now(timezone.utc).isoformat(),
             "kind": kind, "details": details}
    with file.open("a", encoding="utf-8") as out:
        out.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")


def recent(path: str, max_events: int = 20) -> list[dict]:
    file = Path(path)
    if not file.exists():
        return []
    with file.open(encoding="utf-8") as stream:
        lines = stream.readlines()[-max_events:]
    return [json.loads(line) for line in lines if line.strip()]
