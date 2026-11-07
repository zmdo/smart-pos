"""Durable member-parallel workflow with bounded GPU, CPU and model resources."""

import os, signal, subprocess, threading, queue, traceback, shutil, uuid, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from .common import (
    DATA,
    WEB_DATA,
    REPO,
    PYTHON,
    FONT,
    APP_ROOT,
    read,
    save,
    now,
    job_dir,
    sha,
)
from . import store, config, intake, model_gateway

QUEUE = queue.Queue()
LOCK = threading.RLock()
ACTIVE = set()
PROCESSES = {}
STOPPING = threading.Event()
WORKER = None
RESOURCES = {"gpu": threading.BoundedSemaphore(1), "cpu": threading.BoundedSemaphore(2)}
GPU_NODES = {"split", "standardize", "display"}
CPU_NODES = {"review", "training", "testimonial", "life", "reports"}
BP = REPO / "best-practices"
DELIVERY = BP / "body-scan-delivery"
NAMES = {
    "intake": "整理原始素材",
    "classify": "图片分类",
    "split": "拆分硬拼接体测图",
    "standardize": "体测图校正",
    "display": "人物比例与尺寸统一",
    "reports": "读取体测报告",
    "tables": "构建数据对比表",
    "phase": "训练前后分类",
    "report_crop": "报告照片取景",
    "training_evidence": "训练照分析",
    "training": "训练照输出",
    "testimonial_evidence": "感言内容识别",
    "testimonial_layout": "感言取景与隐私遮盖",
    "testimonial": "会员感言输出",
    "life": "筛选生活照",
    "identity": "补全会员与教练信息",
    "review": "准备人工审核",
}


def enqueue(jid, action="preprocess", version=None):
    with LOCK:
        if STOPPING.is_set():
            raise ValueError("服务正在重启，请稍后重试")
        if jid in ACTIVE:
            raise ValueError("该任务正在处理中")
        ACTIVE.add(jid)
    store.patch(jid, status="queued", error=None)
    QUEUE.put((jid, action, version))


def start():
    global WORKER
    STOPPING.clear()
    model_gateway.ENABLED = True
    store.initialize()
    for job in store.listing(include_internal=True):
        if job["status"] in ("processing", "generating", "queued", "uploading"):
            store.patch(
                job["id"],
                status="failed",
                error="服务重启中断了任务，可重试；已完成节点保留",
            )
    WORKER = threading.Thread(target=worker, daemon=True, name="studio-workflow")
    WORKER.start()


def stop():
    """Stop every child process group, including concurrent preview renders."""
    with LOCK:
        STOPPING.set()
        processes = list(PROCESSES.values())
    for proc in processes:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    deadline = time.monotonic() + 3
    while any(p.poll() is None for p in processes) and time.monotonic() < deadline:
        time.sleep(0.05)
    for proc in processes:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    QUEUE.put(None)
    if WORKER:
        WORKER.join(timeout=5)
    model_gateway.stop()


def worker():
    while True:
        task = QUEUE.get()
        if task is None:
            QUEUE.task_done()
            return
        jid, action, version = task
        try:
            if STOPPING.is_set():
                raise RuntimeError("服务重启中断了任务，可重试；已完成节点保留")
            if action == "generate":
                generate(jid, version)
            else:
                preprocess(jid)
        except Exception as exc:
            save(
                job_dir(jid) / "last-error.json",
                {"error": str(exc), "trace": traceback.format_exc()},
                True,
            )
            store.patch(jid, status="failed", error=str(exc)[:600])
        finally:
            with LOCK:
                ACTIVE.discard(jid)
            QUEUE.task_done()


def command(jid, args, log):
    env = dict(
        os.environ,
        PYTHONPATH=str(APP_ROOT) + os.pathsep + str(REPO),
        OPENBLAS_NUM_THREADS="1",
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        PYTHONUNBUFFERED="1",
        CASE_PYTHON=PYTHON,
        STUDIO_NODE_WORKERS="1",
    )
    model = job_dir(jid) / "model.json"
    if model.exists():
        env["STUDIO_MODEL_SETTINGS"] = str(model)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as output:
        with LOCK:
            if STOPPING.is_set():
                raise RuntimeError("服务正在重启，请稍后重试")
            proc = subprocess.Popen(
                [str(x) for x in args],
                # Python puts cwd ahead of PYTHONPATH. The frozen snapshot may
                # also contain an older studio package during staged deploys.
                cwd=(
                    APP_ROOT
                    if len(args) > 2
                    and args[1] == "-m"
                    and str(args[2]).startswith("studio.")
                    else REPO
                ),
                env=env,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            PROCESSES[proc.pid] = proc
        try:
            code = proc.wait()
        finally:
            with LOCK:
                PROCESSES.pop(proc.pid, None)
    if code:
        # Logs stay private; model response bodies/credentials are never sent to the browser.
        raise RuntimeError(
            f"处理节点失败（退出码 {code}），请在历史记录重试；详细日志已保留"
        )


def node(jid, key, fn, skip=False):
    if STOPPING.is_set():
        raise RuntimeError("服务重启中断了任务，可重试；已完成节点保留")
    job = store.get(jid)
    old = next((n for n in job["nodes"] if n["key"] == key), None)
    if old and old["status"] == "complete":
        return Path(old["path"])
    dest = job_dir(jid) / "nodes" / (key + "-" + uuid.uuid4().hex[:8])
    entry = dict(
        key=key,
        name=NAMES.get(key, key),
        status="skipped" if skip else "running",
        path=str(dest),
        started_at=now(),
    )
    store.set_node(jid, entry)
    if skip:
        return None
    resource = "gpu" if key in GPU_NODES else "cpu" if key in CPU_NODES else None
    acquired = False
    try:
        if resource:
            entry.update(status="waiting", resource=resource)
            store.set_node(jid, entry)
            while not RESOURCES[resource].acquire(timeout=0.2):
                if STOPPING.is_set():
                    raise RuntimeError("处理已停止，已完成节点保留")
            acquired = True
            if STOPPING.is_set():
                raise RuntimeError("处理已停止，已完成节点保留")
            entry.update(status="running", resource_acquired_at=now())
            store.set_node(jid, entry)
        fn(dest)
    except Exception:
        entry.update(status="failed", finished_at=now())
        store.set_node(jid, entry)
        raise
    finally:
        if acquired:
            RESOURCES[resource].release()
    entry.update(status="complete", finished_at=now())
    store.set_node(jid, entry)
    return dest


def preprocess(jid):
    from .parallel import run

    run(jid)


def combine_sources(jobfile, pairs, pair_ids, combined):
    original = read(jobfile)
    combined.mkdir(exist_ok=True)
    assets = [a for a in original["assets"] if a["id"] not in pair_ids]
    for source_job, selected in [(jobfile, assets)] + (
        [
            (
                pairs / "dataset/job.json",
                [
                    a
                    for a in read(pairs / "dataset/job.json")["assets"]
                    if a.get("pair_source", {}).get("parent_asset_id") in pair_ids
                ],
            )
        ]
        if pairs
        else []
    ):
        for asset in selected:
            target = combined / "input" / asset["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source_job.parent / "input" / asset["path"], target)
        if source_job != jobfile:
            assets.extend(selected)
    save(combined / "job.json", {**original, "assets": assets})
    return assets


def preprocess_member(jid):
    base = job_dir(jid)
    store.patch(jid, status="processing", error=None, processing_started_at=now())
    cfg = read(base / "settings.json")
    cfg["model"] = config.load()["model"]
    save(base / "settings.json", cfg, True)
    model = base / "model.json"
    save(model, model_gateway.settings(cfg["model"]), True)
    cache = DATA / "cache/website"
    cache.mkdir(parents=True, exist_ok=True)

    def shell(dest, args):
        command(jid, args, dest.with_suffix(".log"))

    def unpack(dest):
        if (base / "import-source.json").exists():
            source = Path(read(base / "import-source.json")["path"])
            intake.inventory(source, dest / "dataset")
        else:
            intake.extract(base / "upload.zip", dest / "extracted")
            intake.inventory(dest / "extracted", dest / "dataset")

    entered = node(jid, "intake", unpack)
    jobfile = entered / "dataset/job.json"
    classified = node(
        jid,
        "classify",
        lambda out: shell(
            out,
            [
                PYTHON,
                "-m",
                "studio.bridge",
                "classify",
                str(jobfile),
                str(model),
                str(cache / "classification"),
                str(out),
            ],
        ),
    )
    audit = classified / "classification-comparison.json"
    original = read(jobfile)
    root = jobfile.parent / "input/私教会员案例项目"
    kinds = {a["class"].get("kind") for a in original["assets"]}
    pair_ids = [
        a["id"]
        for a in original["assets"]
        if a["class"].get("kind") == "body_scan" and a["class"].get("phase") == "both"
    ]

    def body_branch():
        pairs = node(
            jid,
            "split",
            lambda out: shell(
                out,
                [
                    "bash",
                    BP / "body-scan-pairs/scripts/body_scan_pairs/run.sh",
                    "--job",
                    jobfile,
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--cache",
                    cache / "pairs",
                    "--split-only",
                    "--asset-id",
                    *pair_ids,
                ],
            ),
            not pair_ids,
        )
        combined = base / "combined"
        assets = combine_sources(jobfile, pairs, pair_ids, combined)
        body = [a for a in assets if a.get("class", {}).get("kind") == "body_scan"]
        standard = node(
            jid,
            "standardize",
            lambda out: shell(
                out,
                [
                    "bash",
                    BP / "body-scan-wall-v4/scripts/run_body_scan_refined.sh",
                    "--job",
                    combined / "job.json",
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--font",
                    FONT,
                    "--width",
                    cfg["display_width"],
                    "--height",
                    1792,
                ],
            ),
            not body,
        )
        displayed = node(
            jid,
            "display",
            lambda out: shell(
                out,
                [
                    "bash",
                    BP / "body-scan-group-display-v3/run.sh",
                    "--input",
                    standard,
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--visibility-settings",
                    model,
                    "--width",
                    cfg["display_width"],
                    "--workers",
                    min(3, cfg["model_workers"]),
                ],
            ),
            not standard
            or not any(
                r.get("status") == "rectangular"
                for r in read(standard / "summary.json", [])
            ),
        )
        return assets, pairs, displayed

    def report_branch():
        tables = node(
            jid,
            "tables",
            lambda out: shell(
                out,
                [
                    "bash",
                    BP / "body-report-compare/run.sh",
                    "tables",
                    "--input",
                    root,
                    "--audit",
                    audit,
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--cache",
                    cache / "tables",
                    "--workers",
                    cfg["model_workers"],
                ],
            ),
        )
        from .report_bridge import build as report_bundle

        reports = node(jid, "reports", lambda out: report_bundle(tables, out))
        crops = node(
            jid,
            "report_crop",
            lambda out: shell(
                out,
                [
                    PYTHON,
                    "-m",
                    "scripts.report_photo_crop",
                    "--audit",
                    audit,
                    "--input-root",
                    root,
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--cache",
                    cache / "report-crop",
                    "--ratio",
                    "3:4",
                    "--workers",
                    cfg["model_workers"],
                ],
            ),
            not kinds.intersection({"body_report", "training_report"}),
        )
        return tables, reports, crops

    def extras_branch():
        products = {}
        for key, package, kind in [
            ("training", "training_daily", "daily_training"),
            ("testimonial", "testimonial_album", "testimonial"),
        ]:
            evidence = node(
                jid,
                key + "_evidence",
                lambda out, p=package: shell(
                    out,
                    [
                        "bash",
                        DELIVERY / p / "evidence.sh",
                        "--input",
                        root,
                        "--audit",
                        audit,
                        "--out",
                        out,
                        "--settings",
                        model,
                        "--cache",
                        cache / p,
                        "--workers",
                        cfg["model_workers"],
                    ],
                ),
                kind not in kinds,
            )
            if key == "testimonial":
                evidence = node(
                    jid,
                    "testimonial_layout",
                    lambda out: shell(
                        out,
                        [
                            "bash",
                            DELIVERY / package / "annotate.sh",
                            "--input",
                            root,
                            "--evidence",
                            evidence,
                            "--out",
                            out,
                            "--settings",
                            model,
                            "--cache",
                            cache / "testimonial-layout",
                            "--workers",
                            cfg["model_workers"],
                        ],
                    ),
                    not evidence,
                )
            products[key] = node(
                jid,
                key,
                lambda out, p=package, e=evidence: shell(
                    out,
                    [
                        "bash",
                        DELIVERY / p / "run.sh",
                        "--input",
                        root,
                        "--evidence",
                        e,
                        "--out",
                        out,
                        *(["--font", FONT] if p == "testimonial_album" else []),
                    ],
                ),
                not evidence,
            )
        products["life"] = node(
            jid,
            "life",
            lambda out: shell(
                out,
                [
                    "bash",
                    DELIVERY / "life_photos/run.sh",
                    "--input",
                    root,
                    "--audit",
                    audit,
                    "--out",
                    out,
                ],
            ),
        )
        return products

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="member-branch") as pool:
        body_task = pool.submit(body_branch)
        report_task = pool.submit(report_branch)
        extras_task = pool.submit(extras_branch)
        assets, pairs, displayed = body_task.result()
        tables, reports, crops = report_task.result()
        combined = base / "combined"
        sources = {}
        for asset in assets:
            sources[asset["id"]] = {
                "job": str(combined / "job.json"),
                "job_sha256": sha(combined / "job.json"),
            }
            if asset.get("pair_source"):
                report = (
                    pairs
                    / "splits"
                    / asset["pair_source"]["parent_asset_id"]
                    / "report.json"
                )
                sources[asset["id"]].update(
                    split_report=str(report), split_report_sha256=sha(report)
                )
        save(
            base / "source-manifest.json",
            {"schema": "body-scan-source-jobs-v1", "assets": sources},
        )
        phase = node(
            jid,
            "phase",
            lambda out: shell(
                out,
                [
                    "bash",
                    BP / "body-scan-phase-classification/run.sh",
                    "run",
                    "--input",
                    displayed / "display",
                    "--source-manifest",
                    base / "source-manifest.json",
                    "--reports",
                    reports,
                    "--out",
                    out,
                    "--settings",
                    model,
                    "--cache",
                    cache / "phase",
                    "--provider",
                    "qwen",
                ],
            ),
            not displayed,
        )
        products = extras_task.result()

    paths = dict(
        job=str(jobfile),
        audit=str(audit),
        combined=str(combined / "job.json"),
        display=str(displayed / "display") if displayed else None,
        reports=str(reports),
        tables=str(tables),
        crops=str(crops) if crops else None,
        phase=str(phase) if phase else None,
        products={k: str(v) if v else None for k, v in products.items()},
    )
    save(base / "paths.json", paths)

    identity = node(
        jid,
        "identity",
        lambda out: command(
            jid,
            [PYTHON, "-m", "studio.identity", "extract", jid, out],
            out.with_suffix(".log"),
        ),
    )
    paths["identity"] = str(identity)
    save(base / "paths.json", paths)

    def prepare(out):
        out.mkdir()
        command(
            jid,
            [PYTHON, "-m", "studio.bridge", "prepare", jid, str(out)],
            out / "prepare.log",
        )
        data = read(out / "review.json")
        store.save_review(jid, data, store.get(jid)["review_version"])

    node(jid, "review", prepare)
    members = store.review(jid)["members"]
    store.patch(
        jid,
        status="review",
        stage="review",
        progress=100,
        error=None,
        resolved_profile=members[0]["profile"] if len(members) == 1 else None,
    )


def generate(jid, review_version):
    from .review import render_version

    store.patch(jid, status="generating", stage="generate", progress=0)
    result = render_version(jid, review_version)
    store.add_version(jid, result)
    store.patch(
        jid,
        status=(
            "complete"
            if store.get(jid)["review_version"] == review_version
            else "review"
        ),
        current_version=result["id"],
        product_count=sum(len(m["products"]) for m in result["members"]),
        stage="complete",
        progress=100,
    )
