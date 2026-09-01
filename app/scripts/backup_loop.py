"""Daily SQLite backup scheduler intended to run as a sidecar container.

Run with ``python -m app.scripts.backup_loop``. The loop sleeps until the next
configured ``BACKUP_HOUR`` (local time), runs ``services.backup.create_backup``
and then prunes files older than ``BACKUP_RETENTION_DAYS``.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from ..config import BACKUP_HOUR, BACKUP_RETENTION_DAYS
from ..services import backup

logger = logging.getLogger(__name__)


def _seconds_until_next_run(now: datetime, target_hour: int) -> float:
    next_run = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return (next_run - now).total_seconds()


def _run_once() -> None:
    try:
        path = backup.create_backup()
        logger.info("Utworzono backup: %s", path)
    except backup.BackupError as exc:
        logger.error("Backup nie powiódł się: %s", exc)
        return

    try:
        removed = backup.delete_old_backups(BACKUP_RETENTION_DAYS)
        if removed:
            logger.info("Usunięto %d starych kopii zapasowych.", removed)
    except Exception:  # pragma: no cover - guard
        logger.exception("Czyszczenie starych backupów nie powiodło się.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info(
        "Backup scheduler started — godzina backupu: %02d:00, retencja: %d dni.",
        BACKUP_HOUR,
        BACKUP_RETENTION_DAYS,
    )
    while True:
        sleep_seconds = _seconds_until_next_run(datetime.now(), BACKUP_HOUR)
        logger.info("Następny backup za %.0f s.", sleep_seconds)
        time.sleep(sleep_seconds)
        _run_once()


if __name__ == "__main__":
    main()
