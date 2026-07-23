from __future__ import annotations
import json, os, tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HARNESS_DIR = Path('.harness')

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')

def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise ValueError(f'Missing required file: {path}') from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f'Invalid JSON in {path}: {exc}') from exc

def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def task_map(backlog: dict) -> dict[str, dict]:
    return {t['id']: t for t in backlog.get('tasks', [])}

def active_tasks(backlog: dict) -> list[dict]:
    return [t for t in backlog.get('tasks', []) if t.get('status') in {'implementing','verifying','reviewing'}]
