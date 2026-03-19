"""
File state management with locking, atomic writes, and backup rotation.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from filelock import FileLock, Timeout

from .exceptions import LockedError


class StateManager:
    """
    Manages state files with file locking, atomic writes, and backup rotation.

    Keeps 3 backups of each state file. Detects stale locks (>5min mtime).
    """

    LOCK_TIMEOUT_SECONDS = 30
    STALE_LOCK_AGE_SECONDS = 300  # 5 minutes
    MAX_BACKUPS = 3

    def __init__(self, state_dir: str = "~/.openclaw/outreach"):
        """Initialize state manager with given directory."""
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _get_lock_path(self, filename: str) -> Path:
        """Get lock file path for a state file."""
        return self.state_dir / f".{filename}.lock"

    def _get_backup_dir(self, filename: str) -> Path:
        """Get backup directory for a state file."""
        backup_dir = self.state_dir / f".{filename}.backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    def _is_lock_stale(self, lock_path: Path) -> bool:
        """Check if lock file is stale (>5 minutes old)."""
        if not lock_path.exists():
            return False
        mtime = lock_path.stat().st_mtime
        age = datetime.now().timestamp() - mtime
        return age > self.STALE_LOCK_AGE_SECONDS

    def _acquire_lock(self, filename: str) -> FileLock:
        """
        Acquire lock for a state file. Removes stale locks.

        Returns:
            FileLock object

        Raises:
            LockedError if lock cannot be acquired
        """
        lock_path = self._get_lock_path(filename)

        # Remove stale lock
        if self._is_lock_stale(lock_path):
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

        lock = FileLock(str(lock_path), timeout=self.LOCK_TIMEOUT_SECONDS)

        try:
            lock.acquire()
            return lock
        except Timeout:
            raise LockedError(
                f"Cannot acquire lock for {filename}. "
                f"Another process is writing state. Try again in {self.LOCK_TIMEOUT_SECONDS}s."
            )

    def _rotate_backups(self, filename: str) -> None:
        """Keep only MAX_BACKUPS backups. Delete oldest if over limit."""
        backup_dir = self._get_backup_dir(filename)

        # Get all backups sorted by creation time
        backups = sorted(
            backup_dir.glob(f"{filename}.*.backup"),
            key=lambda p: p.stat().st_mtime,
        )

        # Remove oldest backups if over limit
        while len(backups) >= self.MAX_BACKUPS:
            backups[0].unlink()
            backups.pop(0)

    def read(self, filename: str, default: dict = None) -> dict:
        """
        Read state file (no locking required for read).

        Args:
            filename: State file name (e.g. 'config.json')
            default: Default value if file doesn't exist

        Returns:
            Parsed JSON dict
        """
        filepath = self.state_dir / filename
        if not filepath.exists():
            return default or {}

        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            raise ValueError(f"Failed to read {filename}: {e}")

    def write(self, filename: str, data: dict) -> None:
        """
        Write state file with locking and backup rotation.

        Args:
            filename: State file name
            data: Data to write (will be JSON serialized)

        Raises:
            LockedError if lock cannot be acquired
        """
        filepath = self.state_dir / filename
        lock = self._acquire_lock(filename)

        try:
            # Create backup of existing file
            if filepath.exists():
                backup_dir = self._get_backup_dir(filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"{filename}.{timestamp}.backup"
                shutil.copy2(filepath, backup_path)
                self._rotate_backups(filename)

            # Write atomically (write to temp, then rename)
            temp_path = filepath.with_suffix(filepath.suffix + ".tmp")
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)

            temp_path.replace(filepath)  # Atomic on POSIX

        finally:
            lock.release()

    def restore_backup(self, filename: str, backup_num: int = 1) -> None:
        """
        Restore a backup of a state file.

        Args:
            filename: State file name
            backup_num: Which backup to restore (1 = most recent)
        """
        backup_dir = self._get_backup_dir(filename)
        backups = sorted(
            backup_dir.glob(f"{filename}.*.backup"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not backups or len(backups) < backup_num:
            raise ValueError(f"Backup {backup_num} not found for {filename}")

        backup_path = backups[backup_num - 1]
        filepath = self.state_dir / filename

        lock = self._acquire_lock(filename)
        try:
            shutil.copy2(backup_path, filepath)
        finally:
            lock.release()

    def list_backups(self, filename: str) -> list[dict]:
        """
        List all backups for a state file.

        Returns:
            List of dicts with 'timestamp' and 'size' keys
        """
        backup_dir = self._get_backup_dir(filename)
        backups = sorted(
            backup_dir.glob(f"{filename}.*.backup"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        result = []
        for i, backup_path in enumerate(backups, 1):
            stat = backup_path.stat()
            # Extract timestamp from filename (e.g. "config.json.20260319_143022.backup")
            parts = backup_path.stem.split(".")
            timestamp = parts[-1] if len(parts) > 1 else "unknown"

            result.append(
                {
                    "backup_num": i,
                    "timestamp": timestamp,
                    "size_bytes": stat.st_size,
                    "path": str(backup_path),
                }
            )

        return result
