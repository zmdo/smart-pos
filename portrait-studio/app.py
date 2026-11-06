import asyncio, hashlib, hmac, json, re, secrets, shutil, time, socket, ipaddress
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image
from settings import ROOT, DATA, load, save
from origins import is_allowed_origin
from engine import read_job, write_job, update, process_job, MODELS
POOL=ThreadPoolExecutor(max_workers=1,thread_name_prefix="gpu")
AUTH_SECRET=load()["access_code"]
COOKIE=hashlib.sha256(("portrait-session:"+AUTH_SECRET).encode()).hexdigest()
LOGIN_ATTEMPTS={}
ACTIVE_UPLOADS=0
class Options(BaseModel):
    width:int=Field(default=512,ge=128,le=2048)
    height:int=Field(default=768,ge=128,le=2048)
    padding:int=Field(default=8,ge=0,le=30)
    gap:int=Field(default=12,ge=0,le=64)
    confidence:float=Field(default=.35,ge=.1,le=.9)
    mask_enabled:bool=True
    mask_scaled:bool=False
    mask_scale:float=Field(default=1.35,ge=1,le=2.5)
    background:str=Field(default="#f2f0eb",pattern=r"^#[0-9a-fA-F]{6}$")
class Credentials(BaseModel):
    code:str=Field(max_length=200)
class ModelSettings(BaseModel):
    api_key:str=Field(default="",max_length=500)
    base_url:str=Field(default="https://api.deepseek.com",max_length=500)
    model:str=Field(default="deepseek-flash",min_length=1,max_length=120)
def job_dir(job_id):
    if not re.fullmatch(r"[a-f0-9]{24}",job_id): raise HTTPException(404,"任务不存在")
    p=DATA/"jobs"/job_id
    if not (p/"job.json").exists(): raise HTTPException(404,"任务不存在")
    return p
@asynccontextmanager
async def lifespan(app):
    for path in (DATA/"jobs").glob("*/job.json"):
        try:
            j=json.loads(path.read_text())
            if j["status"] in ("running","queued","uploading"):
                j.update(status="interrupted",stage="服务重启中断了任务，请重新提交",finished_at=time.time())
                write_job(j)
        except Exception: pass
    yield
    POOL.shutdown(wait=False,cancel_futures=True)
app=FastAPI(title="四向 · Portrait Studio",docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
@app.middleware("http")
async def auth(request,call_next):
    path=request.url.path
    protected=path.startswith("/api/") and path not in ("/api/login","/api/health")
    if protected and not hmac.compare_digest(request.cookies.get("portrait_session",""),COOKIE):
        return JSONResponse({"detail":"请输入访问码"},401)
    if request.method not in ("GET","HEAD","OPTIONS"):
        origin=request.headers.get("origin")
        if origin and not is_allowed_origin(origin, request.url.scheme, request.headers.get("host", "")):
            return JSONResponse({"detail":"跨站请求已拒绝"},403)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="same-origin"
    if path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
    return response
@app.get("/")
def home(): return FileResponse(ROOT/"static"/"index.html")
app.mount("/static",StaticFiles(directory=ROOT/"static"),name="static")
@app.get("/api/health")
def health(): return {"status":"ok","service":"portrait-studio"}
@app.post("/api/login")
def login(body:Credentials,request:Request):
    ip=request.client.host if request.client else "unknown"
    now=time.monotonic()
    attempts=[t for t in LOGIN_ATTEMPTS.get(ip,[]) if now-t<60]
    if len(attempts)>=12: raise HTTPException(429,"尝试次数过多，请 1 分钟后重试")
    if not hmac.compare_digest(body.code,AUTH_SECRET):
        LOGIN_ATTEMPTS[ip]=attempts+[now]
        raise HTTPException(401,"访问码不正确")
    LOGIN_ATTEMPTS.pop(ip,None)
    response=JSONResponse({"ok":True})
    # The public proxy can omit the HTTPS scheme; browser Origin still carries it.
    secure=(request.headers.get("x-forwarded-proto",request.url.scheme)=="https"
            or request.headers.get("origin","").startswith("https://"))
    response.set_cookie("portrait_session",COOKIE,max_age=604800,httponly=True,secure=secure,samesite="strict")
    return response
@app.post("/api/logout")
def logout():
    response=JSONResponse({"ok":True}); response.delete_cookie("portrait_session"); return response
@app.get("/api/settings")
def settings():
    s=load()
    return {"base_url":s["base_url"],"model":s["model"],"api_key_configured":bool(s["api_key"]),
        "segmentation":"SAM 2.1 Base+","gpu":"NVIDIA CUDA","model_loaded":bool(MODELS)}
def validate_url(url):
    parsed=urlparse(url)
    if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise HTTPException(400,"Base URL 必须是有效 HTTPS 地址")
    try:
        addresses=socket.getaddrinfo(parsed.hostname,parsed.port or 443)
        if any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
            raise HTTPException(400,"不允许访问私有网络地址")
    except socket.gaierror: raise HTTPException(400,"无法解析 API 域名")
@app.put("/api/settings")
def set_settings(body:ModelSettings):
    validate_url(body.base_url)
    s=load(); s.update(base_url=body.base_url.rstrip("/"),model=body.model.strip())
    if body.api_key.strip(): s["api_key"]=body.api_key.strip()
    save(s); return {"ok":True}
@app.post("/api/settings/test")
def test_settings():
    s=load()
    try:
        with httpx.Client(timeout=20,trust_env=False) as c:
            r=c.get(s["base_url"]+"/models",headers={"Authorization":"Bearer "+s["api_key"]})
        if r.status_code!=200: raise HTTPException(400,f"接口返回 HTTP {r.status_code}")
        ids=[x["id"] for x in r.json().get("data",[])]
        return {"ok":True,"models":ids,"model_available":s["model"] in ids}
    except HTTPException: raise
    except Exception: raise HTTPException(400,"连接失败，请检查接口地址和网络")
@app.get("/api/jobs")
def list_jobs():
    jobs=[]
    for p in sorted((DATA/"jobs").glob("*/job.json"),key=lambda p:p.stat().st_mtime,reverse=True)[:100]:
        try:
            j=json.loads(p.read_text())
            jobs.append({k:v for k,v in j.items() if k not in ("records",)})
        except Exception: pass
    return jobs
@app.get("/api/jobs/{job_id}")
def get_job(job_id:str):
    job_dir(job_id); return read_job(job_id)
@app.post("/api/jobs")
async def create_job(archive:UploadFile=File(...),options:str=Form("{}"),sticker:UploadFile|None=File(None)):
    global ACTIVE_UPLOADS
    try: opts=Options.model_validate_json(options)
    except Exception: raise HTTPException(422,"输出参数无效：尺寸 128–2048，留白 0–30%，遮罩倍率 1–2.5")
    active=[j for j in list_jobs() if j["status"] in ("queued","running","uploading")]
    if len(active)+ACTIVE_UPLOADS>=4: raise HTTPException(429,"当前队列已满，请等待任务完成")
    if shutil.disk_usage(DATA).free<5*1024**3: raise HTTPException(507,"剩余存储空间不足 5 GB，请清理旧任务")
    job_id=secrets.token_hex(12); d=DATA/"jobs"/job_id; d.mkdir()
    ACTIVE_UPLOADS+=1
    try:
        size=0
        with (d/"upload").open("wb") as f:
            while chunk:=await archive.read(1024*1024):
                size+=len(chunk)
                if size>1024**3: raise HTTPException(413,"压缩包不可超过 1 GB")
                f.write(chunk)
        if not size: raise HTTPException(400,"上传文件为空")
        if sticker and sticker.filename:
            raw=await sticker.read(10*1024*1024+1)
            if len(raw)>10*1024*1024: raise HTTPException(413,"遮罩图片不可超过 10 MB")
            import io
            try:
                with Image.open(io.BytesIO(raw)) as im:
                    if im.width*im.height>16_000_000: raise ValueError()
                    im.convert("RGBA").save(d/"sticker.png")
            except Exception: raise HTTPException(400,"遮罩必须是有效图片，且不超过 1600 万像素")
        job={"id":job_id,"name":Path(archive.filename or "archive.zip").name,"status":"queued",
            "created_at":time.time(),"stage":"等待 GPU","options":opts.model_dump(),"processed":0,
            "total":0,"stats":{},"sheets":[],"records":[],"upload_size":size}
        write_job(job)
        POOL.submit(process_job,job_id)
        return job
    except Exception:
        shutil.rmtree(d,ignore_errors=True)
        raise
    finally:
        ACTIVE_UPLOADS-=1
        await archive.close()
        if sticker: await sticker.close()
@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id:str):
    job_dir(job_id)
    j=read_job(job_id)
    if j["status"] not in ("queued","running"): raise HTTPException(409,"任务已经结束")
    update(job_id,cancel_requested=True,stage="将在当前模型调用完成后停止")
    return {"ok":True}
@app.delete("/api/jobs/{job_id}")
def delete_job(job_id:str):
    p=job_dir(job_id)
    if read_job(job_id)["status"] in ("queued","running"): raise HTTPException(409,"请先停止任务")
    shutil.rmtree(p); return {"ok":True}
@app.get("/api/jobs/{job_id}/download")
def download(job_id:str):
    p=job_dir(job_id)/"results.zip"
    if not p.exists(): raise HTTPException(404,"结果尚未生成")
    return FileResponse(p,filename=f"portrait-{job_id[:8]}.zip",media_type="application/zip")
@app.get("/api/jobs/{job_id}/files/{filename}")
def output_file(job_id:str,filename:str,download:bool=False):
    d=job_dir(job_id)/"output"
    if not re.fullmatch(r"[a-z0-9_.-]+",filename): raise HTTPException(404)
    p=d/filename
    if not p.is_file(): raise HTTPException(404,"文件不存在")
    return FileResponse(p,filename=filename if download else None)

