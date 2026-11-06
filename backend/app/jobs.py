"""The one slot for heavy work: reading a document or running the browser agent.

Each needs real memory, so they run one at a time. A request that has waited too long for the slot gets a
clear "busy, try again" instead of piling up behind the others until the host's proxy gives up on it.
"""
import os
import threading
from contextlib import contextmanager

QUEUE_SECONDS = float(os.environ.get("HEAVY_QUEUE_SECONDS", "45"))
_slot = threading.Lock()


class Busy(Exception):
    en = "The server is busy with another document or form. Please try again in a minute."
    retry_after = 20


@contextmanager
def heavy(wait: float | None = None):
    if not _slot.acquire(timeout=QUEUE_SECONDS if wait is None else wait):
        raise Busy()
    try:
        yield
    finally:
        _slot.release()
