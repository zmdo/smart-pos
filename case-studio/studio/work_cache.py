"""Per-artifact deduplication and bounded preview workers."""
import threading, weakref

_LOCKS = weakref.WeakValueDictionary()
_GUARD = threading.Lock()
RENDER_SLOTS = threading.BoundedSemaphore(2)
EDITOR_SLOTS = threading.BoundedSemaphore(2)


def lock_for(key):
    with _GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock
