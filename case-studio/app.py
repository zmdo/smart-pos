"""case-studio：会员案例素材生产（第一阶段：素材体检 / dry-run）。

只做「解包 → 归一 → 去重 → 质量 → 分类 → 报告抽取 → 归并 → 产出决策 → 报告」，
不做渲染（渲染是下一阶段）。
"""
import asyncio, hashlib, hmac, json, re, secrets, shutil, threading, time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import classify, facts as facts_mod, plan as plan_mod, preprocess
from archives import extract
from settings import BATCHES, DATA, ROOT, load

STATE_LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="batch")
CFG = load()
TOKEN = CFG["access_token"]
COOKIE = hashlib.sha256(("case-session:" + TOKEN).encode()).hexdigest()
LOGIN_HITS = {}

MAX_UPLOAD = 2 * 1024 ** 3


# ---------------------------------------------------------------- job state
def jdir(batch_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{24}", batch_id):
        raise HTTPException(404, "批次不存在")
    p = BATCHES / batch_id
    if not (p / "job.json").exists():
        raise HTTPException(404, "批次不存在")
    return p


def read_job(batch_id: str) -> dict:
    with STATE_LOCK:
        return json.loads((jdir(batch_id) / "job.json").read_text())


def write_job(job: dict) -> None:
    with STATE_LOCK:
        path = BATCHES / job["id"] / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job, ensure_ascii=False))
        tmp.replace(path)


def patch(batch_id: str, **values) -> dict:
    with STATE_LOCK:
        job = read_job(batch_id)
        job.update(values)
        write_job(job)
        return job


def log_line(batch_id: str, msg: str) -> None:
    with STATE_LOCK:
        p = BATCHES / batch_id / "run.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")


# ---------------------------------------------------------------- pipeline
STORE_RE = re.compile(r".*店$")
NON_PRODUCTION = ("参考模板", "生产标准", "说明文件")


def split_path(rel: str) -> dict:
    """把相对路径拆成 店/会员。参考模板、标准说明这类目录不算生产素材。"""
    parts = rel.split("/")
    dirs = parts[:-1]
    if any(any(k in d for k in NON_PRODUCTION) for d in dirs):
        return {"store": "（模板/标准包）", "member_dir": dirs[-1] if dirs else "",
                "member": (dirs[-1] if dirs else "未分类"), "coach": None, "note": "",
                "non_production": True}
    store_idx = next((i for i, p in enumerate(dirs) if STORE_RE.match(p)), None)
    if store_idx is None:
        store = dirs[-2] if len(dirs) >= 2 else (dirs[0] if dirs else "未分组")
        member = dirs[-1] if dirs else "未分组"
    else:
        store = dirs[store_idx]
        member = dirs[store_idx + 1] if len(dirs) > store_idx + 1 else "（店根目录）"
    info = plan_mod.split_member(member)
    return {"store": store, "member_dir": member,
            "member": info["name"], "coach": info["coach"], "note": info["note"],
            "non_production": False}


def package_kind(paths: list) -> str:
    joined = "\n".join(paths)
    flags = set()
    if "参考模板" in joined:
        flags.add("template")
    if "生产标准" in joined or "生产手册" in joined:
        flags.add("standard")
    if re.search(r"[^\n]*店/", joined):
        flags.add("store")
    if len(flags) > 1:
        return "mixed"
    return next(iter(flags)) if flags else "unknown"


def run_batch(batch_id: str) -> None:
    base = BATCHES / batch_id
    try:
        patch(batch_id, status="running", stage="解包", started_at=time.time())
        result = extract(base / "upload.zip", base / "input", log=lambda m: log_line(batch_id, m))
        files = result["files"]
        patch(batch_id, total_files=len(files), skipped_files=result["skipped"])

        # ---- 归一（这一遍只算指标，不判定丢弃；丢弃要等分类结果）
        patch(batch_id, stage="归一化")
        seen_sha, assets = {}, []
        images = [f for f in files if f["kind"] == "image"]
        for i, f in enumerate(images, 1):
            src = base / "input" / f["path"]
            sha = preprocess.sha256_file(src)
            meta = split_path(f["path"])
            asset = {"id": f"a{i:04d}", "path": f["path"], "kind": "image",
                     "sha256": sha, **meta}
            if sha in seen_sha:
                asset.update(status="duplicate", duplicate_of=seen_sha[sha]["id"], quality={})
                assets.append(asset)
                continue
            out = preprocess.process(src, base / "work", asset["id"], CFG["quality"])
            asset.update(out)
            asset["status"] = "ok" if out.get("ok") else "quarantined"
            seen_sha[sha] = asset
            assets.append(asset)
            if i % 10 == 0:
                patch(batch_id, processed=i, total_images=len(images), stage=f"归一化 {i}/{len(images)}")

        # ---- 文档 / 视频登记
        for j, f in enumerate([x for x in files if x["kind"] in ("document", "video")], 1):
            meta = split_path(f["path"])
            assets.append({"id": f"d{j:04d}", "path": f["path"], "kind": f["kind"],
                           "size": f["size"], "status": "ok", **meta})

        # ---- 分类（只处理 ok 的图片）
        patch(batch_id, stage="视觉分类")
        todo = [{"sha256": a["sha256"], "thumb": str(base / a["renditions"]["thumb"]),
                 "id": a["id"]} for a in assets
                if a["kind"] == "image" and a.get("status") in ("ok", "dropped") and a.get("renditions")]
        by_id = {a["id"]: a for a in assets}

        def progress(done, total):
            if done % 5 == 0 or done == total:
                patch(batch_id, stage=f"视觉分类 {done}/{total}", classified=done)

        res = classify.classify_all(todo, CFG, CFG["classify_concurrency"], progress)
        for a in assets:
            if a["kind"] != "image":
                continue
            c = res["results"].get(a.get("sha256"))
            a["class"] = c or {"kind": "unknown", "confidence": 0,
                               "reason": res["errors"].get(a.get("sha256"), "分类失败")}
        patch(batch_id, classify_errors=len(res["errors"]))

        # ---- 质量判定（按类别）+ 近似去重（分类之后做，避免把"前后对照"当成重复）
        patch(batch_id, stage="质量判定与去重")
        qcfg = CFG["quality"]
        for a in assets:
            if a["kind"] != "image" or a.get("status") != "ok":
                continue
            q = a.get("quality") or {}
            kind = (a.get("class") or {}).get("kind")
            reasons = []
            if q.get("sharpness", 999) < qcfg.get("sharpness", 20):
                reasons.append("blurry")
            mean_luma = q.get("mean_luma", 128)
            if mean_luma < qcfg.get("mean_dark", 30) or mean_luma > qcfg.get("mean_bright", 245):
                reasons.append("bad_exposure")
            elif q.get("hi_ratio", 0) > qcfg.get("clip_ratio", 0.8) or q.get("lo_ratio", 0) > qcfg.get("clip_ratio", 0.8):
                reasons.append("bad_exposure")
            if q.get("min_side", 99999) < qcfg["min_side"]:
                reasons.append("low_res")
            if kind == "body_scan" and 0 <= q.get("subject_ratio", -1) < qcfg.get("subject_ratio", 0.02):
                reasons.append("subject_too_small")
            q["drop_reasons"] = reasons
            q["status"] = "dropped" if reasons else "ok"
            a["quality"] = q
            if reasons:
                a["status"] = "dropped"

        seen = []
        for a in assets:
            if a["kind"] != "image" or a.get("status") != "ok" or not a.get("phash"):
                continue
            kind = (a.get("class") or {}).get("kind")
            if kind in ("body_report", "testimonial", "unknown", None):
                continue  # 报告/感言是成对或截图，不做近似去重
            w, h = a.get("width") or 0, a.get("height") or 0
            ar = (w / h) if h else 0
            dup = None
            for b in seen:
                if (b.get("class") or {}).get("kind") != kind:
                    continue
                bw, bh = b.get("width") or 0, b.get("height") or 0
                bar = (bw / bh) if bh else 0
                if bar and ar and abs(ar - bar) / bar > 0.08:
                    continue
                if preprocess.hamming(a["phash"], b["phash"]) <= 4:
                    dup = b
                    break
            if dup:
                a["status"] = "duplicate"
                a["duplicate_of"] = dup["id"]
            else:
                seen.append(a)

        # ---- 对比图切分（一张图里有前后两人时，切成两张分别作为训练前/训练后）
        patch(batch_id, stage="对比图切分")
        plan_assets = []
        split_count = 0
        for a in assets:
            c = a.get("class") or {}
            if (a["kind"] == "image" and c.get("phase") == "both"
                    and a.get("status") in ("ok", "dropped") and a.get("width")):
                sp = plan_mod.compute_split(a.get("persons") or [], a.get("width"), a.get("height"))
                w, h = a["width"], a["height"]
                a["split"] = {**sp, "before": [0, 0, sp["x"], h], "after": [sp["x"], 0, w, h]}
                if a.get("status") == "ok":
                    split_count += 1
                for ph, box in (("before", [0, 0, sp["x"], h]), ("after", [sp["x"], 0, w, h])):
                    if box[2] - box[0] < 10:
                        continue
                    twin = dict(a)
                    twin["id"] = a["id"] + ("b" if ph == "before" else "a")
                    twin["crop"] = box
                    twin["class"] = dict(c, phase=ph)
                    twin["split"] = a["split"]
                    plan_assets.append(twin)
            else:
                plan_assets.append(a)
        patch(batch_id, split_images=split_count)

        # ---- 报告解析（每个会员取一份 docx/pdf）
        facts_by_member = {}
        for a in assets:
            if a["kind"] != "document":
                continue
            if Path(a["path"]).suffix.lower() not in (".docx", ".pdf"):
                continue
            key = (a["store"], a["member"])
            if key in facts_by_member:
                continue
            info = facts_mod.parse(base / "input" / a["path"])
            facts_by_member[key] = info
            a["facts_ok"] = bool(info.get("ok"))

        # ---- 归并 + 决策
        patch(batch_id, stage="产出决策")
        members = plan_mod.build(plan_assets, facts_by_member)
        summary = {
            "assets": len(assets),
            "images": len(images),
            "duplicates": sum(1 for a in assets if a.get("status") == "duplicate"),
            "dropped": sum(1 for a in assets if a.get("status") == "dropped"),
            "quarantined": sum(1 for a in assets if a.get("status") == "quarantined"),
            "members": len(members),
            "outputs_possible": sum(m["produced_count"] for m in members),
            "gaps": sum(len(m["gaps"]) for m in members),
            "review": sum(len(m["review"]) for m in members),
            "video_deferred": sum(1 for a in assets if a["kind"] == "video"),
            "split_images": split_count,
        }
        patch(batch_id, status="completed", stage="体检完成", finished_at=time.time(),
              summary=summary, package=package_kind([f["path"] for f in files]),
              assets=[public_asset(a) for a in assets], members=members)
        log_line(batch_id, f"完成：{summary}")
    except Exception as e:
        patch(batch_id, status="failed", stage="失败", error=f"{type(e).__name__}: {e}"[:400],
              finished_at=time.time())
        log_line(batch_id, f"失败：{e}")


def public_asset(a: dict) -> dict:
    keep = ("id", "path", "kind", "status", "store", "member", "coach", "note",
            "duplicate_of", "quality", "width", "height", "class", "facts_ok", "split")
    out = {k: a.get(k) for k in keep if k in a}
    out["thumb"] = a.get("renditions", {}).get("thumb") if a.get("renditions") else None
    return out


# ---------------------------------------------------------------- web app
@asynccontextmanager
async def lifespan(app):
    for p in BATCHES.glob("*/job.json"):
        try:
            j = json.loads(p.read_text())
            if j.get("status") in ("queued", "running"):
                j.update(status="interrupted", stage="服务重启中断，请重跑", finished_at=time.time())
                write_job(j)
        except Exception:
            pass
    yield
    POOL.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="Case Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def guard(request: Request, call_next):
    path = request.url.path
    protected = path.startswith("/api/") and path not in ("/api/login", "/api/health")
    if protected and not hmac.compare_digest(request.cookies.get("case_session", ""), COOKIE):
        return JSONResponse({"detail": "请输入访问令牌"}, 401)
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    if path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "case-studio", "token_configured": bool(TOKEN)}


@app.post("/api/login")
def login(body: dict, request: Request):
    ip = request.client.host if request.client else "?"
    now = time.monotonic()
    hits = [t for t in LOGIN_HITS.get(ip, []) if now - t < 60]
    if len(hits) >= 12:
        raise HTTPException(429, "尝试过多，请 1 分钟后重试")
    if not hmac.compare_digest(str(body.get("token", "")), TOKEN):
        LOGIN_HITS[ip] = hits + [now]
        raise HTTPException(401, "令牌不正确")
    LOGIN_HITS.pop(ip, None)
    resp = JSONResponse({"ok": True})
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    resp.set_cookie("case_session", COOKIE, max_age=604800, httponly=True,
                    secure=secure, samesite="strict")
    return resp


@app.get("/api/batches")
def list_batches():
    out = []
    for p in sorted(BATCHES.glob("*/job.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
        try:
            j = json.loads(p.read_text())
            out.append({k: j.get(k) for k in ("id", "name", "status", "stage", "created_at",
                                              "finished_at", "summary", "package")})
        except Exception:
            pass
    return out


@app.post("/api/batches")
async def create_batch(archive: UploadFile = File(...), mode: str = Form("dryrun")):
    batch_id = secrets.token_hex(12)
    d = BATCHES / batch_id
    d.mkdir(parents=True)
    size = 0
    with (d / "upload.zip").open("wb") as f:
        while chunk := await archive.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, "压缩包不可超过 2 GB")
            f.write(chunk)
    if not size:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "空文件")
    job = {"id": batch_id, "name": Path(archive.filename or "archive.zip").name,
           "status": "queued", "stage": "排队中", "created_at": time.time(),
           "mode": mode, "upload_size": size}
    write_job(job)
    POOL.submit(run_batch, batch_id)
    await archive.close()
    return job


@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str):
    return read_job(batch_id)


@app.get("/api/batches/{batch_id}/report.md")
def report(batch_id: str):
    job = read_job(batch_id)
    if job["status"] not in ("completed", "partial"):
        raise HTTPException(409, "尚未完成")
    return PlainTextResponse(render_report(job), media_type="text/markdown; charset=utf-8")


@app.post("/api/batches/{batch_id}/cancel")
def cancel(batch_id: str):
    job = read_job(batch_id)
    if job["status"] not in ("queued", "running"):
        raise HTTPException(409, "已结束")
    patch(batch_id, cancel_requested=True, stage="将尽快停止")
    return {"ok": True}


@app.get("/api/batches/{batch_id}/thumb/{asset_id}")
def thumb(batch_id: str, asset_id: str):
    job = read_job(batch_id)
    asset = next((a for a in job.get("assets", []) if a["id"] == asset_id), None)
    if not asset or not asset.get("thumb"):
        raise HTTPException(404)
    p = BATCHES / batch_id / asset["thumb"]
    if not p.is_file():
        raise HTTPException(404)
    return FileResponse(p)


def render_report(job: dict) -> str:
    s = job.get("summary", {})
    lines = [f"# 素材体检报告 · {job['name']}", "",
             f"- 批次：`{job['id']}`　模式：{job.get('mode')}",
             f"- 文件：{s.get('images', 0)} 张图片 / {job.get('total_files', 0)} 个文件"
             f"（重复 {s.get('duplicates', 0)}，低质丢弃 {s.get('dropped', 0)}，隔离 {s.get('quarantined', 0)}）",
             f"- 会员：{s.get('members', 0)} 人　可出成品：{s.get('outputs_possible', 0)} 张"
             f"　缺口：{s.get('gaps', 0)} 项　待确认：{s.get('review', 0)} 项",
             f"- 视频（本期不处理）：{s.get('video_deferred', 0)} 个", ""]
    for m in job.get("members", []):
        c = m["counts"]
        lines.append(f"## {m['store']} · {m['name']}")
        lines.append("")
        lines.append("| 素材 | 数量 | 说明 |")
        lines.append("| --- | --- | --- |")
        lines.append(f"| 体测图 | {c['body_scan']} | 正/侧/背 × 前/后 |")
        lines.append(f"| 体测报告 | {c['body_report']} | 需要 2 张 |")
        lines.append(f"| 训练成果报告 | {c['training_report']} | docx/pdf |")
        lines.append(f"| 日常训练图 | {c['daily_training']} | 需要 3 张 |")
        lines.append(f"| 生活照 | {c['life_photo']} | 需要 2 张 |")
        lines.append(f"| 会员感言 | {c['testimonial']} | 需要 1 张 |")
        if c["video_deferred"]:
            lines.append(f"| 视频（跳过） | {c['video_deferred']} | 本期不处理 |")
        lines.append("")
        lines.append("| 体测视图 | 训练前 | 训练后 | 背景 | 来源 |")
        lines.append("| --- | :-: | :-: | --- | --- |")
        for key in ("front", "side", "back"):
            sl = m["slots"].get(key) or {}
            if not (sl.get("before") or sl.get("after")):
                continue
            mark = lambda ok: "✅" if ok else "—"
            bg = sl.get("background") or {}
            bg_txt = " / ".join(sorted({v for v in (bg.get("before"), bg.get("after"))
                                        if v and v not in ("—",)})) or "未识别"
            fs = sl.get("from_split") or {}
            src = "对比图切分" if (fs.get("before") or fs.get("after")) else "单图"
            lines.append(f"| {sl.get('label', key)} | {mark(sl.get('before'))} | "
                         f"{mark(sl.get('after'))} | {bg_txt} | {src} |")
        lines.append("")
        if m.get("dropped"):
            lines.append(f"**质量丢弃**：{m['dropped']} 张（可在界面强制使用或更换素材）")
            lines.append("")
        lines.append(f"**能出 {m['produced_count']} 张**：" +
                     ("、".join(o["label"] for o in m["outputs"] if o["ok"]) or "无"))
        if m["gaps"]:
            lines.append("")
            lines.append("**缺什么：**")
            for g in m["gaps"]:
                lines.append(f"- {g['label']} — {g['reason']}")
        if m["review"]:
            lines.append("")
            lines.append("**待人工确认：**")
            for r in m["review"]:
                lines.append(f"- {r['id']}：{r['reason']}")
        if m["facts"]["warnings"]:
            lines.append("")
            lines.append("**数据校验：**")
            for w in m["facts"]["warnings"]:
                lines.append(f"- ⚠️ {w}")
        lines.append("")
    return "\n".join(lines)
