import logging
import threading
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
APP_LOG_PATH = LOG_DIR / "app.log"
LOG_DIR.mkdir(exist_ok=True)

_LOGGER = logging.getLogger("sentinel_notifier.runtime")
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False

if not _LOGGER.handlers:
    handler = RotatingFileHandler(
        APP_LOG_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(handler)


def log_file(event, details="", exc=None):
    """Write a thread-safe runtime event with bounded on-disk retention."""
    try:
        from datetime import datetime

        ts = datetime.now().isoformat(timespec="seconds")
        message = f"[{ts}] [{threading.current_thread().name}] {event}"
        if details:
            message += f" | {details}"
        if exc is not None:
            message += "\n" + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        _LOGGER.info(message)
    except Exception:
        pass
