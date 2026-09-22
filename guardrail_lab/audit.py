"""Metadata-only JSONL audit. Never write prompts, responses, API keys, or tool arguments."""
from datetime import datetime, timezone
from pathlib import Path
import json
import threading
from .guards import GuardError


class Audit:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def emit(self, events, run_id, category, result, code, detail):
        event = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "run_id": run_id, "category": category, "result": result,
                 "code": code, "detail": detail}
        try:
            with self.lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                if self.path.exists() and self.path.stat().st_size > 2_000_000:
                    self.path.replace(self.path.with_name("audit.previous.jsonl"))
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                    handle.flush()
        except OSError:
            raise GuardError("Audit", "audit_unavailable", "The local audit log is unavailable. The action was stopped; check write access to logs/.") from None
        events.append(event)
        return event
