"""Source-bound classification; the approved prompt is independent of the UI."""

import os, sys
from concurrent.futures import ThreadPoolExecutor
from .common import REPO, read, save, sha
from .prompts import CLASSIFY_PROMPT, CLASSIFY_VERSION


def normalize(v):
    kind = v.get("kind", "other")
    if kind not in (
        "body_scan",
        "body_report",
        "training_report",
        "daily_training",
        "life_photo",
        "testimonial",
        "other",
    ):
        kind = "other"
    rejection = None
    if kind == "body_scan" and (
        v.get("wall_background") is not True
        or v.get("body_scan_pose") is not True
        or v.get("training_activity") is True
        or v.get("background") in ("mirror", "outdoor")
    ):
        rejection = "body_scan_requires_wall_and_static_pose"
        kind = "daily_training" if v.get("training_activity") else "other"
    result = {
        k: v.get(k)
        for k in (
            "view",
            "background",
            "phase",
            "wall_background",
            "body_scan_pose",
            "training_activity",
            "wall_evidence",
            "people",
            "already_masked",
            "is_screenshot",
            "reason",
        )
    }
    result.update(
        kind=kind,
        classification_rule=CLASSIFY_VERSION,
        rule_rejection=rejection,
        confidence=max(0, min(1, float(v.get("confidence") or 0))),
    )
    if kind != "body_scan":
        result.update(view=None, phase=None, background=None)
    elif result["view"] not in (
        "front",
        "back",
        "side",
        "side_left",
        "side_right",
        None,
    ):
        result["view"] = None
    return result


def run(job_path, settings, cache, out):
    sys.path.insert(0, str(REPO / "best-practices/body-scan-delivery"))
    from snapshot import verify_integrity

    verify_integrity()
    from training_daily.client import MeasuredClient
    import cv2

    client = MeasuredClient(settings, cache, "qwen")
    job = read(job_path)

    def work(asset):
        source = job_path.parent / "input" / asset["path"]
        im = cv2.imread(str(source))
        if im is None:
            raise ValueError("无法读取图片：" + asset["id"])
        value, trace = client.ask([im], CLASSIFY_PROMPT, CLASSIFY_VERSION)
        label = normalize(value)
        asset["class"] = label
        return dict(
            asset_id=asset["id"],
            store=asset["store"],
            member=asset["member"],
            source=str(source),
            source_sha256=sha(source),
            reference_material=False,
            qwen=label,
            trace=trace,
        )

    with ThreadPoolExecutor(
        max_workers=int(os.environ.get("STUDIO_NODE_WORKERS", "3"))
    ) as pool:
        rows = list(pool.map(work, job["assets"]))
    save(job_path, job)
    save(out / "classification-comparison.json", rows)
