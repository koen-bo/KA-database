"""
Climate Adaptation Knowledge Base - Main Orchestrator

This is the main entry point for running the pipeline.
Can be run locally or via GitHub Actions.

Usage:
    python main.py           # Run full ingestion pipeline
    python main.py --test    # Run tests only (no ingestion)
"""

import sys
import json
import os
import socket
from datetime import datetime, timedelta

from modules.ingest import run_ingestion
import config


LOCK_STALE_AFTER = timedelta(hours=2)


class IngestionLock:
    """Simple filesystem lock to prevent overlapping ingestion runs."""

    def __init__(self, lock_path: str, stale_after: timedelta):
        self.lock_path = lock_path
        self.stale_after = stale_after
        self.acquired = False

    def acquire(self) -> bool:
        """Acquire lock; return False when a fresh lock already exists."""
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)

        try:
            return self._create_lock_file()
        except FileExistsError:
            pass

        # Existing lock: check staleness
        try:
            lock_mtime = datetime.fromtimestamp(os.path.getmtime(self.lock_path))
        except FileNotFoundError:
            # Race: lock disappeared between checks, retry once.
            return self.acquire()
        except OSError as e:
            print(f"[WARNING] Could not read lock metadata ({self.lock_path}): {e}")
            print("[WARNING] Skipping run to avoid overlap.")
            return False

        age = datetime.now() - lock_mtime
        if age < self.stale_after:
            print(f"[WARNING] Lock exists and is fresh ({self.lock_path}, age={age}). Skipping run.")
            return False

        print(f"[WARNING] Stale lock detected ({self.lock_path}, age={age}). Replacing lock and continuing.")
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"[WARNING] Could not remove stale lock ({self.lock_path}): {e}")
            print("[WARNING] Skipping run to avoid overlap.")
            return False

        try:
            return self._create_lock_file()
        except FileExistsError:
            print(f"[WARNING] Lock was recreated by another process ({self.lock_path}). Skipping run.")
            return False

    def _create_lock_file(self) -> bool:
        """Create lock file atomically and write metadata."""
        payload = {
            "timestamp": datetime.now().isoformat(),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
        }
        fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
            f.write("\n")
        self.acquired = True
        print(f"[LOCK] Lock acquired: {self.lock_path}")
        return True

    def release(self) -> None:
        """Release lock if held."""
        if not self.acquired:
            return
        try:
            os.remove(self.lock_path)
            print(f"[LOCK] Lock released: {self.lock_path}")
        except FileNotFoundError:
            print(f"[LOCK] Lock already removed: {self.lock_path}")
        except OSError as e:
            print(f"[WARNING] Could not remove lock file ({self.lock_path}): {e}")
        finally:
            self.acquired = False


def main():
    """Run the Climate Monitor pipeline."""
    
    # Check for test mode
    if "--test" in sys.argv:
        print("Running in test mode...")
        from test_pipeline import main as run_tests
        run_tests()
        return
    
    # Run the full ingestion pipeline
    print("\n" + "#" * 60)
    print("#  CLIMATE ADAPTATION KNOWLEDGE BASE")
    print("#  Automated Policy Document Monitor")
    print("#" * 60)

    lock_path = os.path.join(config.DATA_DIR, "ingestion.lock")
    lock = IngestionLock(lock_path=lock_path, stale_after=LOCK_STALE_AFTER)
    if not lock.acquire():
        return

    try:
        # Run ingestion (this also initializes the database)
        stats = run_ingestion()

        # Report results
        if stats["entries_stored"] > 0:
            print(f"\n[SUCCESS] Added {stats['entries_stored']} new documents!")
        else:
            print("\n[INFO] No new relevant documents found today.")

        print("\nPipeline completed successfully.")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
