"""Member isolation, resumable scheduling and deterministic review aggregation."""

import copy, os, shutil, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from . import config, intake, model_gateway, store
from .common import job_dir, now, read, save

MEMBER_WORKERS = 2


def completed(job, key):
    return next(
        (n for n in job["nodes"] if n["key"] == key and n["status"] == "complete"), None
    )


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def partition(jid, entered):
    """Keep all images/documents of one member together, preserving asset IDs."""
    from .workflow import NAMES, STOPPING

    parent = store.get(jid)
    source = Path(entered) / "dataset/job.json"
    original = read(source)
    source_root = source.parent / "input/私教会员案例项目"
    prior = {j["member_group"]["directory"]: j for j in store.children(jid)}
    cfg = read(job_dir(jid) / "settings.json")
    cfg["model_workers"] = 1  # Branches share the global three-request relay.
    cls = completed(parent, "classify")
    splits = completed(parent, "split")
    audit = read(Path(cls["path"]) / "classification-comparison.json") if cls else []
    for index, group in enumerate(original["groups"], 1):
        if STOPPING.is_set():
            raise RuntimeError("处理已停止，已完成会员保留")
        assets = [
            copy.deepcopy(a)
            for a in original["assets"]
            if a["directory"] == group["directory"]
        ]
        member = dict(group, id=f"m{index:03d}", image_count=len(assets))
        child = prior.get(group["directory"])
        if child and completed(child, "intake"):
            continue
        child = child or store.create(
            group["directory"], cfg, parent=jid, member=member
        )
        base = job_dir(child["id"]) / "seed"
        root = base / "dataset/input/私教会员案例项目"
        for directory in (group["directory"], "logo"):
            folder = source_root / directory
            if folder.is_dir():
                for path in folder.rglob("*"):
                    if path.is_file():
                        copy_file(path, root / path.relative_to(source_root))
        save(
            base / "dataset/job.json",
            {**original, "groups": [group], "assets": assets, "excluded": []},
        )

        def seed(key, path):
            store.set_node(
                child["id"],
                dict(
                    key=key,
                    name=NAMES[key],
                    path=str(path),
                    status="complete",
                    started_at=now(),
                    finished_at=now(),
                    reused=True,
                ),
            )

        if cls:
            ids = {a["id"] for a in assets}
            rows = [copy.deepcopy(r) for r in audit if r["asset_id"] in ids]
            if {r["asset_id"] for r in rows} != ids:
                raise ValueError("已完成分类与会员素材不一致")
            by_id = {a["id"]: a for a in assets}
            for row in rows:
                row["source"] = str(
                    base / "dataset/input" / by_id[row["asset_id"]]["path"]
                )
            save(base / "classification/classification-comparison.json", rows)
            seed("classify", base / "classification")
        if splits and any(
            a.get("class", {}).get("phase") == "both"
            and a["class"].get("kind") == "body_scan"
            for a in assets
        ):
            seed("split", Path(splits["path"]))
        # Mark intake last so an interrupted partition can be safely retried.
        seed("intake", base)
        store.patch(
            child["id"], status="queued", stage="queued", progress=0, error=None
        )
    children = store.children(jid)
    expected = {g["directory"] for g in original["groups"]}
    if {j["member_group"]["directory"] for j in children} != expected:
        raise ValueError("会员任务与原始分组不一致")
    return children


def process_member(child):
    from .workflow import STOPPING, preprocess_member

    if STOPPING.is_set():
        return
    try:
        preprocess_member(child["id"])
    except Exception as exc:
        save(
            job_dir(child["id"]) / "last-error.json",
            {"error": str(exc), "trace": traceback.format_exc()},
            True,
        )
        failed = [
            n["name"]
            for n in store.get(child["id"])["nodes"]
            if n["status"] == "failed"
        ]
        prefix = "、".join(failed) + "：" if failed else ""
        store.patch(child["id"], status="failed", error=(prefix + str(exc))[:600])


def merge(jid):
    members = []
    for child in store.children(jid):
        if child["status"] != "review" or not child["review_version"]:
            raise ValueError("仍有会员未完成预处理")
        review = store.review(child["id"])
        if len(review["members"]) != 1:
            raise ValueError("会员处理结果越过分组边界")
        member = copy.deepcopy(review["members"][0])
        if member["directory"] != child["member_group"]["directory"]:
            raise ValueError("会员结果与原始目录不一致")
        member["id"] = child["member_group"]["id"]
        for row in member["_engine"]["rows"]:
            row["group_id"] = member["id"]
        store.copy_media(child["id"], jid)
        members.append(member)
    parent = store.get(jid)
    entered = Path(completed(parent, "intake")["path"])
    original = read(entered / "dataset/job.json")
    store.save_review(
        jid,
        {
            "schema": "case-studio-review-v1",
            "members": members,
            "excluded": original["excluded"],
        },
        parent["review_version"],
    )
    save(
        job_dir(jid) / "member-workflow.json",
        {
            "version": "member-parallel-v1",
            "members": [
                {
                    "id": c["member_group"]["id"],
                    "job": c["id"],
                    "directory": c["member_group"]["directory"],
                }
                for c in store.children(jid)
            ],
            "model_resources": model_gateway.stats(),
        },
    )


def run(jid):
    from .workflow import node, STOPPING

    base = job_dir(jid)
    store.patch(
        jid, status="processing", stage="intake", error=None, parallel_members=True
    )

    def unpack(out):
        if (base / "import-source.json").exists():
            intake.inventory(
                Path(read(base / "import-source.json")["path"]), out / "dataset"
            )
        else:
            intake.extract(base / "upload.zip", out / "extracted")
            intake.inventory(out / "extracted", out / "dataset")

    entered = node(jid, "intake", unpack)
    children = partition(jid, entered)
    store.patch(jid, stage="members", member_count=len(children), progress=5)
    pending = [
        c for c in children if c["status"] != "review" or not c["review_version"]
    ]
    for child in pending:
        store.patch(child["id"], status="queued", error=None)
    with ThreadPoolExecutor(
        max_workers=MEMBER_WORKERS, thread_name_prefix="member-preprocess"
    ) as pool:
        futures = [pool.submit(process_member, child) for child in pending]
        for future in as_completed(futures):
            future.result()
    if STOPPING.is_set():
        raise RuntimeError("处理已停止，已完成会员与节点保留")
    failed = [c for c in store.children(jid) if c["status"] != "review"]
    if failed:
        raise RuntimeError(
            f"{len(failed)} 位会员未完成；其他会员结果已保留，可重试未完成会员"
        )
    merge(jid)
    store.patch(jid, status="review", stage="review", progress=100, error=None)


def summary(jid):
    """Public list metadata, excluding internal job IDs and filesystem paths."""
    children = store.children(jid)
    groups = []
    for child in children:
        group = child["member_group"]
        status = (
            "complete"
            if child["status"] == "review" and child["review_version"]
            else (
                "running"
                if child["status"] == "processing"
                else "failed" if child["status"] == "failed" else "queued"
            )
        )
        profile = group
        if status == "complete":
            profile = child.get("resolved_profile") or group
        nodes = [
            {k: n.get(k) for k in ("key", "name", "status", "resource")}
            for n in child["nodes"]
            if n["status"] in ("running", "waiting")
        ]
        groups.append(
            dict(
                id=group["id"],
                store=group["store"],
                directory=group["directory"],
                member=profile.get("name") or group["member"],
                coach=profile.get("coach", ""),
                image_count=group["image_count"],
                status=status,
                progress=100 if status == "complete" else child["progress"],
                steps=nodes,
                error=child.get("error"),
            )
        )
    return {"limit": MEMBER_WORKERS, "gpu_limit": 1, "model_limit": 3, "groups": groups}
