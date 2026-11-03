"""Local bounded audit of decisions and actual adapter outcomes, without content."""
from datetime import datetime, timezone
import json
from threading import RLock
from .paths import PRIVATE, atomic_json, ordinary_tree


class ActionJournal:
    def __init__(self, path=None):
        self.path = path
        self.lock = RLock()
        self.rows = []
        if path and path.exists():
            try:
                if ordinary_tree(path).stat().st_size <= 1048576:
                    data = json.loads(path.read_text(encoding='utf-8'))
                    if isinstance(data, list):
                        self.rows = [r for r in data[-200:] if isinstance(r, dict)]
            except (OSError, ValueError):
                pass

    def record(self, name, target, decision, result=None):
        with self.lock:
            self.rows.append({'at': datetime.now(timezone.utc).isoformat(), 'tool': name,
                              'target': target, 'decision': decision,
                              'execution_status': result.execution_status if result else None,
                              'observed_state': result.observed_state if result else None,
                              'success': result.success if result else False})
            self.rows = self.rows[-200:]
            if self.path:
                atomic_json(self.path, self.rows)

    def snapshot(self):
        with self.lock:
            return list(self.rows)


journal = ActionJournal(PRIVATE / 'actions.json')
