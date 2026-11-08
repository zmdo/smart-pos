"""Case Studio: new three-page application, independent of the retired website."""

import asyncio, hmac, time, uuid, shutil
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from studio import store, config, review, workflow, copywriter, parallel, privacy, stickers, storage_backup
from studio.common import APP_ROOT, DATA, WEB_DATA, PUBLIC_URL, job_dir, read, save
from studio.render_errors import RenderInputError


@asynccontextmanager
async def lifespan(app):
    workflow.start()
    config.load()
    storage_backup.start()
    yield
    await asyncio.to_thread(workflow.stop)
    await asyncio.to_thread(storage_backup.stop)


app = FastAPI(title="会员案例工作台", lifespan=lifespan, docs_url=None, redoc_url=None)
ATTEMPTS = defaultdict(deque)


def origin(value):
    p = urlsplit(value)
    return (
        p.scheme.lower(),
        (p.hostname or "").lower(),
        p.port or (443 if p.scheme == "https" else 80),
    )


@app.middleware("http")
async def access(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            supplied = request.headers.get("origin")
            allowed = {origin(PUBLIC_URL), origin(str(request.base_url))}
            if not supplied or origin(supplied) not in allowed:
                return JSONResponse(
                    {"detail": "请求来源不匹配，请从网站地址重新打开页面"}, 403
                )
        if path not in ("/api/session", "/api/health") and not await asyncio.to_thread(
            store.session_valid, request.cookies.get("studio_session")
        ):
            return JSONResponse({"detail": "请先输入访问码"}, 401)
    try:
        response = await call_next(request)
    except (KeyError, ValueError) as exc:
        return JSONResponse({"detail": str(exc)}, 400)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.exception_handler(ValueError)
async def bad_value(request, exc):
    return JSONResponse(
        {"detail": str(exc)}, 409 if isinstance(exc, store.Conflict) else 400
    )


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({"detail": str(exc)}, 404)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "case-studio-workflow-v1"}


@app.get("/api/session")
def session(request: Request):
    return {"authenticated": store.session_valid(request.cookies.get("studio_session"))}


@app.post("/api/session")
async def login(request: Request):
    body = await request.json()
    ip = request.client.host if request.client else "unknown"
    q = ATTEMPTS[ip]
    now = time.monotonic()
    while q and q[0] < now - 300:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "尝试次数过多，请五分钟后重试")
    q.append(now)
    if not hmac.compare_digest(
        str(body.get("code", "")), (await asyncio.to_thread(config.load))["access_token"]
    ):
        raise HTTPException(401, "访问码不正确")
    q.clear()
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        "studio_session",
        await asyncio.to_thread(store.issue_session),
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https"
        or request.headers.get("origin", "").startswith("https://"),
        max_age=604800,
    )
    return response


@app.delete("/api/session")
def logout(request: Request):
    store.revoke(request.cookies.get("studio_session"))
    response = JSONResponse({"ok": True})
    response.delete_cookie("studio_session")
    return response


@app.get("/api/settings")
def settings():
    return config.public()


@app.get("/api/stickers")
def sticker_catalog():
    return [stickers.public(s) for s in stickers.catalog()]


@app.get("/api/stickers/{sid}/image")
def sticker_image(sid: str):
    return FileResponse(stickers.get(sid)["path"], media_type="image/png")


@app.post("/api/jobs/{jid}/members/{mid}/privacy")
async def prepare_privacy(jid: str, mid: str, request: Request):
    return privacy.start(jid, mid, await request.json())


@app.get("/api/jobs/{jid}/members/{mid}/privacy")
def privacy_status(jid: str, mid: str):
    return privacy.status(jid, mid)


@app.put("/api/settings")
async def settings_save(request: Request):
    return config.update(await request.json())


@app.post("/api/settings/logo")
async def logo(file: UploadFile = File(...)):
    from PIL import Image

    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("Logo 不能超过 10 MB")
    import io

    with Image.open(io.BytesIO(data)) as im:
        if im.width * im.height > 20_000_000:
            raise ValueError("Logo 像素过大")
        folder = WEB_DATA / "logos"
        folder.mkdir(exist_ok=True)
        path = folder / (uuid.uuid4().hex + ".png")
        im.convert("RGBA").save(path)
    config.set_logo(str(path))
    return config.public()


def public_job(job):
    value = dict(job)
    value["nodes"] = [{k: v for k, v in n.items() if k != "path"} for n in job["nodes"]]
    value.pop("legacy_source", None)
    if job.get("parallel_members"):
        value["preprocessing"] = parallel.summary(job["id"])
        groups = value["preprocessing"]["groups"]
        value["nodes"] = [n for n in value["nodes"] if n["key"] == "intake"]
        if groups and not job["review_version"]:
            value["progress"] = min(
                99,
                round(
                    5 + 90 * sum(g["progress"] for g in groups) / (100 * len(groups))
                ),
            )
    return value


@app.get("/api/jobs")
def jobs():
    return [public_job(j) for j in store.listing()]


@app.get("/api/jobs/{jid}")
def job(jid: str):
    return public_job(store.get(jid))


@app.post("/api/jobs")
async def upload(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise ValueError("请上传 ZIP 压缩包")
    item = store.create(file.filename, config.snapshot())
    jid = item["id"]
    size = 0
    try:
        with (job_dir(jid) / "upload.zip").open("wb") as out:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > 4 * 1024**3:
                    raise ValueError("压缩包不能超过 4 GB")
                out.write(block)
        workflow.enqueue(jid)
        return public_job(store.get(jid))
    except Exception as exc:
        store.patch(jid, status="failed", error=str(exc))
        raise
    finally:
        await file.close()


@app.post("/api/jobs/{jid}/retry")
def retry(jid: str):
    j = store.get(jid)
    if j["status"] != "failed":
        raise ValueError("只有失败任务可以重试")
    workflow.enqueue(
        jid,
        (
            "generate"
            if j["stage"] == "generate" and j["review_version"]
            else "preprocess"
        ),
        j["review_version"] or None,
    )
    return public_job(store.get(jid))


@app.get("/api/jobs/{jid}/review")
def get_review(jid: str):
    return review.public(store.review(jid))


@app.patch("/api/jobs/{jid}/members/{mid}")
async def save_member(jid: str, mid: str, request: Request, compact: bool = False):
    body = await request.json()
    def update():
        result = review.update(jid, mid, body)
        if compact:
            return dict(version=result["version"], member=review.public(next(m for m in result["members"] if m["id"] == mid)))
        return review.public(result)
    return await asyncio.to_thread(update)


@app.post("/api/jobs/{jid}/preview/{mid}")
async def preview(jid: str, mid: str, request: Request):
    body = await request.json()
    version = body.get("version")
    if type(version) is not int:
        raise ValueError("缺少审核版本")
    try:
        return await asyncio.to_thread(
            review.preview, jid, mid, version, body.get("section")
        )
    except RenderInputError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError:
        label = {'three_views':'完整六图', 'vs':'同朝向对比图', 'cover':'会员案例封面', 'table':'体测对比表'}.get(body.get('section'), '成品')
        raise HTTPException(422, label + "预览生成失败，详细原因已记录在任务日志中。请稍后重试；若仍失败，请联系维护人员查看日志。")


@app.get("/api/jobs/{jid}/previews/{mid}")
def latest_previews(jid: str, mid: str):
    return review.preview_latest(jid, mid)


@app.post("/api/jobs/{jid}/members/{mid}/mask-editor")
async def open_mask_editor(jid: str, mid: str, request: Request):
    from studio import mask_editor
    body = await request.json()
    if not isinstance(body, dict) or set(body) != {"version", "section"}:
        raise ValueError("遮罩面板参数无效")
    try:
        return await asyncio.to_thread(mask_editor.load, jid, mid, body["version"], body["section"])
    except RenderInputError as exc:
        raise HTTPException(422, str(exc))
    except RuntimeError:
        raise HTTPException(422, "遮罩面板生成失败，请检查取景与头部准备状态后重试")


@app.patch("/api/jobs/{jid}/members/{mid}/mask-editor")
async def save_mask_editor(jid: str, mid: str, request: Request):
    from studio import mask_editor
    return review.public(await asyncio.to_thread(mask_editor.update, jid, mid, await request.json()))


@app.get("/api/cover-ai/templates")
def copy_templates():
    return copywriter.templates()


@app.post("/api/cover-ai/templates")
async def add_copy_template(request: Request):
    return copywriter.save_template(await request.json())


@app.put("/api/cover-ai/templates/{tid}")
async def update_copy_template(tid: str, request: Request):
    return copywriter.save_template(await request.json(), tid)


@app.delete("/api/cover-ai/templates/{tid}")
def delete_copy_template(tid: str):
    copywriter.delete_template(tid)
    return {"ok": True}


@app.post("/api/jobs/{jid}/members/{mid}/cover-ai")
async def cover_ai(jid: str, mid: str, request: Request):
    try:
        return await asyncio.to_thread(
            copywriter.generate, jid, mid, await request.json()
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/jobs/{jid}/generate")
async def generate(jid: str, request: Request):
    body = await request.json()
    j = store.get(jid)
    if body.get("version") != j["review_version"] or not j["review_version"]:
        raise store.Conflict("请刷新并保存最新审核内容")
    workflow.enqueue(jid, "generate", j["review_version"])
    return public_job(store.get(jid))


@app.get("/api/jobs/{jid}/versions")
def versions(jid: str):
    return store.versions(jid)


@app.get("/api/jobs/{jid}/media/{mid}")
def media(jid: str, mid: str):
    return FileResponse(store.media_file(jid, mid))


@app.get("/api/jobs/{jid}/download/{vid}")
def download(
    jid: str,
    vid: str,
    member: str | None = None,
    types: list[str] | None = Query(default=None),
):
    path, name = review.archive(jid, vid, member, types)
    return FileResponse(path, filename=name, media_type="application/zip")


def legacy_items():
    items = []
    for folder in sorted((DATA / "batches").glob("*"), reverse=True):
        if not folder.is_dir() or not (folder / "input").is_dir():
            continue
        old = read(folder / "job.json", {})
        items.append(
            {
                "id": folder.name,
                "name": old.get("name") or old.get("filename") or folder.name,
                "status": "legacy",
                "created_at": old.get("created_at"),
                "asset_count": len(old.get("assets", [])),
            }
        )
    return items


@app.get("/api/legacy")
def legacy():
    return legacy_items()


@app.post("/api/legacy/{lid}/import")
def import_legacy(lid: str):
    if lid not in {r["id"] for r in legacy_items()}:
        raise KeyError("旧批次不存在")
    j = store.create("历史素材 · " + lid[:8], config.snapshot(), lid)
    save(
        job_dir(j["id"]) / "import-source.json",
        {"path": str(DATA / "batches" / lid / "input")},
        True,
    )
    workflow.enqueue(j["id"])
    return public_job(store.get(j["id"]))


app.mount("/static", StaticFiles(directory=APP_ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(APP_ROOT / "static/index.html")
