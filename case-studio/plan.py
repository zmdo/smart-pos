"""产出决策：依赖矩阵 → 每个会员能出哪几张 + 缺口清单（纯规则，可单测）。"""
import re
from collections import Counter, defaultdict

VIEW_LABEL = {"front": "正视图", "side": "侧视图", "back": "后视图"}
VIEW_KEY = {"front": "F", "side": "S", "back": "B"}
SIDE_PREF = {"side_left": 0, "side_right": 1, "side": 2}
SIDE_ZH = {"side_left": "左侧", "side_right": "右侧", "side": "左右未判定"}
BG_ZH = {"grid_board": "网格板", "white_wall": "白墙", "wood": "木板墙",
         "mirror": "镜面", "outdoor": "户外", "other": "其他"}

CJK_NAME = re.compile(r"^[\u4e00-\u9fa5]{2,4}$")
SUFFIX = re.compile(r"[（(][^）)]*[）)]")


def split_member(folder: str) -> dict:
    """目录名 → {raw, name, coach, missing_note}"""
    raw = folder.strip()
    note = ""
    m = SUFFIX.search(raw)
    if m:
        note = m.group(0)
    clean = SUFFIX.sub("", raw).strip()
    coach, member = None, clean
    if "-" in clean:
        first, last = clean.split("-", 1)
        if CJK_NAME.match(last.strip()):
            coach, member = first.strip(), last.strip()
        else:
            member = clean
    return {"raw": raw, "name": member, "coach": coach, "note": note}


def _cls(a: dict) -> dict:
    return a.get("class") or {}


def _phase_slots(scans: list) -> dict:
    """把一个视图的若干图归到 before/after 槽位。

    返回 {before: asset|None, after: asset|None, extras: n, ambiguous: bool}
    """
    before = after = None
    extras = 0
    ambiguous = False
    for a in scans:
        p = _cls(a).get("phase")
        if p == "both":
            before = before or a
            after = after or a
        elif p == "before":
            before = before or a
            extras += 1
        elif p == "after":
            after = after or a
            extras += 1
        else:  # unknown
            extras += 1
    if not before and not after:
        # 两张阶段未知 → 视为一对，顺序待确认
        if len(scans) >= 2:
            before, after = scans[0], scans[1]
            ambiguous = True
        elif scans:
            before = scans[0]
            ambiguous = True
    elif before and after and before is after:
        ambiguous = True
    return {"before": before, "after": after, "extras": extras, "ambiguous": ambiguous}


def compute_split(persons, w, h):
    """对比图（一张里前后两人）找中缝：优先两人框之间的空隙，其次中心点，最后画面中线。"""
    if not w or w <= 0:
        return {"x": 0, "method": "none"}
    method = "center"
    x = w / 2.0
    boxes = [b for b in (persons or []) if len(b) == 4]
    if len(boxes) >= 2:
        boxes = sorted(boxes, key=lambda b: (b[0] + b[2]) / 2)
        left, right = boxes[0], boxes[-1]
        if left[2] < right[0]:
            x = (left[2] + right[0]) / 2.0
            method = "gap"
        else:
            x = ((left[0] + left[2]) / 2.0 + (right[0] + right[2]) / 2.0) / 2.0
            method = "centers"
    if not (0.3 * w <= x <= 0.7 * w):
        x = w / 2.0
        method = "center"
    return {"x": int(round(x)), "method": method}


def build_member(name: str, store: str, assets: list, facts: dict | None) -> dict:
    dropped = [a for a in assets if a.get("status") == "dropped"]
    assets = [a for a in assets if a.get("status") in ("ok", "forced")]
    scans = [a for a in assets if _cls(a).get("kind") == "body_scan"]
    by_view = defaultdict(list)
    for a in scans:
        v = _cls(a).get("view") or "unknown"
        by_view["side" if v.startswith("side") else v].append(a)
    for key in by_view:
        by_view[key].sort(key=lambda a: SIDE_PREF.get(_cls(a).get("view"), 9))
    slots = {v: _phase_slots(by_view[v]) for v in ("front", "side", "back")}

    def view_zh(view):
        s = slots[view]
        picked = s["before"] or s["after"]
        side = _cls(picked).get("view") if picked else None
        if view == "side" and side in SIDE_ZH:
            return VIEW_LABEL[view] + "（" + SIDE_ZH[side] + "）"
        return VIEW_LABEL[view]

    def bg_of(asset):
        return BG_ZH.get((_cls(asset) or {}).get("background") or "", "未识别") if asset else "—"

    body_reports = [a for a in assets if _cls(a).get("kind") == "body_report"]
    training_docs = [a for a in assets if _cls(a).get("kind") == "training_report"]
    docs = [a for a in assets if a["kind"] == "document"]
    daily = [a for a in assets if _cls(a).get("kind") == "daily_training"]
    life = [a for a in assets if _cls(a).get("kind") == "life_photo"]
    testimony = [a for a in assets if _cls(a).get("kind") == "testimonial"]
    videos = [a for a in assets if a["kind"] == "video"]

    outputs, gaps, review = [], [], []

    def add(oid, label, ok, needs=None, reason=None, extra=None):
        item = {"id": oid, "label": label, "ok": bool(ok)}
        if needs:
            item["needs"] = needs
        if reason:
            item["reason"] = reason
        if extra:
            item.update(extra)
        outputs.append(item)
        if not ok:
            gaps.append({"id": oid, "label": label, "reason": reason or "缺素材",
                         "needs": needs or []})

    for view in ("front", "side", "back"):
        s = slots[view]
        zh = VIEW_LABEL[view]   # 文件名严格对齐模板，不把"左/右"写进成品名
        add(f"{VIEW_KEY[view]}1", f"会员体测{zh}（训练前）", bool(s["before"]),
            ["训练前照片"], "缺该视图的训练前照片")
        add(f"{VIEW_KEY[view]}2", f"会员体测{zh}（训练后）", bool(s["after"]),
            ["训练后照片"], "缺该视图的训练后照片")
        add(f"{VIEW_KEY[view]}3", f"会员体测{zh}（训练前VS训练后）",
            bool(s["before"] and s["after"]), ["训练前照片", "训练后照片"],
            "缺少同一视图的训练前/后对照")
        if s["ambiguous"] and (s["before"] or s["after"]):
            review.append({"id": f"{VIEW_KEY[view]}3", "reason": "训练前/后顺序待确认"})
        b_bg, a_bg = bg_of(s["before"]), bg_of(s["after"])
        if s["before"] and s["after"] and b_bg != a_bg and "未识别" not in (b_bg, a_bg):
            review.append({"id": f"{VIEW_KEY[view]}3",
                           "reason": f"训练前后背景不一致（{b_bg} vs {a_bg}）"})

    all_six = all(slots[v]["before"] and slots[v]["after"] for v in ("front", "side", "back"))
    missing_views = [view_zh(v) for v in ("front", "side", "back")
                     if not (slots[v]["before"] and slots[v]["after"])]
    add("O10", "会员体测三视图对比拼图", all_six,
        ["三视图 × 训练前/后 共 6 张"],
        f"缺少 {('、'.join(missing_views))} 的训练前/后对照" if missing_views else None)

    metrics = (facts or {}).get("metrics") or {}
    has_metric = bool(metrics.get("weight")) and bool(metrics.get("fat"))
    add("O11", "会员案例封面",
        bool(slots["front"]["before"] and slots["front"]["after"] and has_metric),
        ["正视训练前/后", "指标数据"],
        "缺指标数据" if not has_metric else "缺正视训练前/后照片")

    add("O12", "会员生活照（训练前VS训练后）", len(life) >= 2, ["生活照 2 张"],
        f"只有 {len(life)} 张生活照" if life else "缺生活照")
    add("O13", "会员感言", len(testimony) >= 1, ["感言截图"], "缺会员感言截图")
    add("O14", "会员训练报告", len(training_docs) >= 1 or bool(facts and facts.get("ok")),
        ["训练成果报告 docx/pdf"], "缺训练成果报告文件")
    add("O15", "会员体测报告&训练报告文件", len(body_reports) >= 1, ["体测报告照片"],
        "缺体测报告照片")

    daily_n = min(3, len(daily))
    for i in range(1, daily_n + 1):
        add(f"O16-{i}", f"会员训练日常{i}", True)
    if daily_n == 0:
        why = "只有视频素材，本期不处理（D12）" if videos else "缺日常训练图"
        gaps.append({"id": "O16", "label": "会员训练日常1..3", "reason": why, "needs": ["日常训练图"]})

    produced = [o["id"] for o in outputs if o["ok"]]
    return {
        "name": name, "store": store,
        "counts": {
            "body_scan": len({a.get("path") for a in scans}), "body_report": len(body_reports),
            "training_report": len(training_docs), "daily_training": len(daily),
            "life_photo": len(life), "testimonial": len(testimony),
            "video_deferred": len(videos), "document": len(docs),
        },
        "slots": {v: {"before": bool(slots[v]["before"]), "after": bool(slots[v]["after"]),
                      "ambiguous": slots[v]["ambiguous"],
                      "label": view_zh(v),
                      "from_split": {"before": bool(slots[v]["before"] and slots[v]["before"].get("split")),
                                     "after": bool(slots[v]["after"] and slots[v]["after"].get("split"))},
                      "background": {"before": bg_of(slots[v]["before"]),
                                     "after": bg_of(slots[v]["after"])}} for v in slots},
        "outputs": outputs, "produced": produced, "produced_count": len(produced),
        "gaps": gaps, "review": review, "dropped": len(dropped),
        "facts": {"ok": bool(facts and facts.get("ok")),
                  "store": (facts or {}).get("store"),
                  "member": (facts or {}).get("member"),
                  "warnings": (facts or {}).get("warnings", [])},
    }


def build(assets: list, facts_by_member: dict) -> list:
    groups = defaultdict(lambda: defaultdict(list))
    for a in assets:
        if a.get("non_production"):
            continue
        groups[a["store"]][a["member"]].append(a)
    out = []
    for store in sorted(groups):
        for member in sorted(groups[store]):
            out.append(build_member(member, store, groups[store][member],
                                    facts_by_member.get((store, member))))
    return out
