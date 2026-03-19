"""
File state management with locking, atomic writes, and backup rotation.
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from filelock import FileLock, Timeout


class StateManager:
    """Manages JSON state files with file locking and atomic writes."""

    LOCK_TIMEOUT = 30
    STALE_LOCK_AGE = 300  # 5 minutes
    MAX_BACKUPS = 3

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def read(self, filename: str) -> dict:
        filepath = self.state_dir / filename
        if not filepath.exists():
            return {}
        with open(filepath) as f:
            return json.load(f)

    def write(self, filename: str, data: dict) -> None:
        filepath = self.state_dir / filename
        lock_path = self.state_dir / f".{filename}.lock"

        # Remove stale locks
        if lock_path.exists():
            age = datetime.now().timestamp() - lock_path.stat().st_mtime
            if age > self.STALE_LOCK_AGE:
                lock_path.unlink(missing_ok=True)

        lock = FileLock(str(lock_path), timeout=self.LOCK_TIMEOUT)
        try:
            lock.acquire()
        except Timeout:
            raise RuntimeError(f"Cannot acquire lock for {filename}. Try again.")

        try:
            # Backup existing
            if filepath.exists():
                backup_dir = self.state_dir / f".{filename}.backups"
                backup_dir.mkdir(exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(filepath, backup_dir / f"{filename}.{ts}.backup")
                # Rotate
                backups = sorted(backup_dir.glob(f"{filename}.*.backup"), key=lambda p: p.stat().st_mtime)
                while len(backups) > self.MAX_BACKUPS:
                    backups.pop(0).unlink()

            # Atomic write
            tmp = filepath.with_suffix(filepath.suffix + ".tmp")
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            tmp.replace(filepath)
        finally:
            lock.release()
