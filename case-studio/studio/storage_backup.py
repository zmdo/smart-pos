"""Keep consistent local SQLite snapshots on the persistent data volume."""
import logging, os, sqlite3, threading, uuid
from contextlib import closing
from .common import DB_PATH, DB_BACKUP, WEB_DATA

_STOP = threading.Event()
_LOCK = threading.Lock()
_THREAD = None


def backup():
    if DB_PATH == WEB_DATA / 'studio.sqlite3':
        return
    with _LOCK:
        DB_BACKUP.parent.mkdir(parents=True, exist_ok=True)
        temp = DB_BACKUP.with_name('snapshot-'+uuid.uuid4().hex+'.sqlite3')
        try:
            with closing(sqlite3.connect(DB_PATH)) as src, closing(sqlite3.connect(temp)) as dst:
                src.backup(dst)
                dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                dst.execute('PRAGMA journal_mode=DELETE')
                if dst.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database backup validation failed')
            os.chmod(temp, 0o600)
            os.replace(temp, DB_BACKUP)
        finally:
            temp.unlink(missing_ok=True)


def _run():
    # data_version on a persistent connection also sees writes from child processes.
    connection = sqlite3.connect(DB_PATH)
    last = None
    try:
        while not _STOP.is_set():
            current = connection.execute('PRAGMA data_version').fetchone()[0]
            if current != last:
                try:
                    backup()
                    last = current
                except Exception:
                    logging.exception('Persistent database snapshot failed; will retry')
            _STOP.wait(15)
    finally:
        connection.close()


def start():
    global _THREAD
    if DB_PATH == WEB_DATA / 'studio.sqlite3' or (_THREAD and _THREAD.is_alive()):
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=_run, name='studio-db-backup', daemon=True)
    _THREAD.start()


def stop():
    _STOP.set()
    if _THREAD:
        _THREAD.join()
    backup()
