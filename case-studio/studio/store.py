"""Durable job state, immutable review snapshots and bounded media references."""

import json, secrets, sqlite3, time
from contextlib import contextmanager
from .common import WEB_DATA, DATA, DB_PATH, now, job_dir, sha, contained, media_path


class Conflict(ValueError):
    pass


@contextmanager
def db(write=False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        yield conn
        if write:
            conn.commit()
    except Exception:
        if write:
            conn.rollback()
        raise
    finally:
        conn.close()


def initialize():
    if DB_PATH != WEB_DATA / "studio.sqlite3" and not DB_PATH.exists() and (WEB_DATA / "studio.sqlite3").exists():
        raise RuntimeError("本地审核数据库尚未迁移，请先执行 migrate_runtime.py")
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(
            """CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(job TEXT,version INTEGER,data TEXT NOT NULL,PRIMARY KEY(job,version));
CREATE TABLE IF NOT EXISTS media(job TEXT,id TEXT,path TEXT NOT NULL,sha TEXT NOT NULL,PRIMARY KEY(job,id));
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS versions(job TEXT,id TEXT,data TEXT NOT NULL,PRIMARY KEY(job,id));
CREATE TABLE IF NOT EXISTS preview_latest(job TEXT,member TEXT,section TEXT,data TEXT NOT NULL,PRIMARY KEY(job,member,section));
CREATE TABLE IF NOT EXISTS preview_imported(job TEXT,member TEXT,PRIMARY KEY(job,member));"""
        )


def create(name, settings, legacy=None, parent=None, member=None):
    jid = secrets.token_hex(12)
    base = job_dir(jid)
    base.mkdir(parents=True)
    data = dict(
        id=jid,
        name=name[:200],
        status="uploading",
        stage="upload",
        progress=0,
        created_at=now(),
        updated_at=now(),
        nodes=[],
        review_version=0,
        current_version=None,
        member_count=0,
        product_count=0,
        error=None,
        legacy_source=legacy,
    )
    if parent:
        data.update(parent_id=parent, member_group=member)
    from .common import save

    save(base / "settings.json", settings, True)
    with db(True) as c:
        c.execute(
            "INSERT INTO jobs VALUES(?,?)", (jid, json.dumps(data, ensure_ascii=False))
        )
    return data


def get(jid):
    job_dir(jid)
    with db() as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
    if not row:
        raise KeyError("任务不存在")
    return json.loads(row["data"])


def patch(jid, **values):
    with db(True) as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError("任务不存在")
        data = json.loads(row["data"])
        data.update(values, updated_at=now())
        c.execute(
            "UPDATE jobs SET data=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), jid),
        )
    return data


def listing(include_internal=False):
    with db() as c:
        rows = [json.loads(r["data"]) for r in c.execute("SELECT data FROM jobs")]
    return sorted(
        [r for r in rows if include_internal or not r.get("parent_id")],
        key=lambda r: r["created_at"],
        reverse=True,
    )


def children(jid):
    return sorted(
        (r for r in listing(True) if r.get("parent_id") == jid),
        key=lambda r: r["member_group"]["id"],
    )


def set_node(jid, entry):
    """Branches update different nodes in one transaction, without lost writes."""
    with db(True) as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError("任务不存在")
        data = json.loads(row["data"])
        nodes = [n for n in data["nodes"] if n["key"] != entry["key"]] + [entry]
        running = [n for n in nodes if n["status"] in ("running", "waiting")]
        data.update(
            nodes=nodes,
            stage=(running[-1] if running else entry)["key"],
            progress=min(
                95,
                round(
                    100
                    * sum(n["status"] in ("complete", "skipped") for n in nodes)
                    / 17
                ),
            ),
            updated_at=now(),
        )
        c.execute(
            "UPDATE jobs SET data=? WHERE id=?",
            (json.dumps(data, ensure_ascii=False), jid),
        )
    return data


def copy_media(source, target):
    with db(True) as c:
        c.execute(
            "INSERT OR IGNORE INTO media(job,id,path,sha) SELECT ?,id,path,sha FROM media WHERE job=?",
            (target, source),
        )


def review(jid, version=None):
    if version is None:
        version = get(jid)["review_version"]
    with db() as c:
        row = c.execute(
            "SELECT data FROM reviews WHERE job=? AND version=?", (jid, version)
        ).fetchone()
    if not row:
        raise KeyError("审核数据尚未就绪")
    return json.loads(row["data"])


def save_review(jid, data, expected):
    with db(True) as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise KeyError("任务不存在")
        job = json.loads(row["data"])
        if job["review_version"] != expected:
            raise Conflict("审核内容已在另一处修改，请刷新后重试")
        version = expected + 1
        data = dict(data, version=version, updated_at=now())
        c.execute(
            "INSERT INTO reviews VALUES(?,?,?)",
            (jid, version, json.dumps(data, ensure_ascii=False)),
        )
        job.update(
            review_version=version, member_count=len(data["members"]), updated_at=now()
        )
        if job["status"] not in ("processing", "generating"):
            job["status"] = "review"
        c.execute(
            "UPDATE jobs SET data=? WHERE id=?",
            (json.dumps(job, ensure_ascii=False), jid),
        )
    return data


def media(jid, path):
    path = media_path(path)
    if not path.is_file():
        raise ValueError("图片文件不存在")
    import hashlib

    mid = hashlib.sha256(str(path).encode()).hexdigest()[:24]
    with db(True) as c:
        current = c.execute(
            "SELECT sha FROM media WHERE job=? AND id=?", (jid, mid)
        ).fetchone()
        if not current:
            c.execute(
                "INSERT INTO media VALUES(?,?,?,?)", (jid, mid, str(path), sha(path))
            )
    return mid


def latest_previews(jid, mid):
    # Import old persistent pointers once; legacy product/media files stay valid.
    with db() as c:
        imported = c.execute("SELECT 1 FROM preview_imported WHERE job=? AND member=?", (jid, mid)).fetchone()
    if not imported:
        from .common import read
        legacy = read(job_dir(jid) / "previews-v2" / mid / "latest.json", {})
        with db(True) as c:
            for section, result in legacy.items():
                c.execute("INSERT OR IGNORE INTO preview_latest VALUES(?,?,?,?)", (jid, mid, section, json.dumps(result)))
            c.execute("INSERT OR IGNORE INTO preview_imported VALUES(?,?)", (jid, mid))
    with db() as c:
        rows = c.execute("SELECT section,data FROM preview_latest WHERE job=? AND member=?", (jid, mid)).fetchall()
    result = {}
    for row in rows:
        value = json.loads(row['data'])
        try:
            for p in value['products']:
                media_file(jid, p['media'])
        except KeyError:
            continue  # A lost temporary disk can regenerate previews from durable sources.
        result[row['section']] = value
    return result


def set_latest_preview(jid, mid, section, result, version):
    latest_previews(jid, mid)
    with db(True) as c:
        row = c.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        if json.loads(row['data'])['review_version'] == version:
            c.execute("INSERT OR REPLACE INTO preview_latest VALUES(?,?,?,?)", (jid, mid, section, json.dumps(result)))


def media_file(jid, mid):
    with db() as c:
        row = c.execute(
            "SELECT path FROM media WHERE job=? AND id=?", (jid, mid)
        ).fetchone()
    if not row:
        raise KeyError("文件不存在")
    path = media_path(row["path"])
    if not path.is_file():
        raise KeyError("文件不存在")
    return path


def add_version(jid, version):
    with db(True) as c:
        c.execute(
            "INSERT INTO versions VALUES(?,?,?)",
            (jid, version["id"], json.dumps(version, ensure_ascii=False)),
        )


def versions(jid):
    with db() as c:
        rows = [
            json.loads(r["data"])
            for r in c.execute(
                "SELECT data FROM versions WHERE job=? ORDER BY id DESC", (jid,)
            )
        ]
    return rows


def version(jid, vid):
    with db() as c:
        row = c.execute(
            "SELECT data FROM versions WHERE job=? AND id=?", (jid, vid)
        ).fetchone()
    if not row:
        raise KeyError("成品版本不存在")
    return json.loads(row["data"])


def issue_session():
    import hashlib

    token = secrets.token_urlsafe(36)
    with db(True) as c:
        c.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
        c.execute(
            "INSERT INTO sessions VALUES(?,?)",
            (hashlib.sha256(token.encode()).hexdigest(), time.time() + 7 * 86400),
        )
    return token


def session_valid(token):
    import hashlib

    if not token:
        return False
    with db() as c:
        row = c.execute(
            "SELECT expires FROM sessions WHERE token=?",
            (hashlib.sha256(token.encode()).hexdigest(),),
        ).fetchone()
    return bool(row and row["expires"] > time.time())


def revoke(token):
    import hashlib

    with db(True) as c:
        c.execute(
            "DELETE FROM sessions WHERE token=?",
            (hashlib.sha256((token or "").encode()).hexdigest(),),
        )
