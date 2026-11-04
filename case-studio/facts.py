"""报告解析：训练成果报告 docx/pdf → 门店/会员信息 + 指标表 + 一致性校验。"""
import re
from pathlib import Path

FIELDS = {
    "时间": ("days", "天", "date"),
    "身高": ("height", "cm", "num"),
    "体重": ("weight", "kg", "num"),
    "体脂率": ("fat", "%", "num"),
    "BMI": ("bmi", "", "num"),
    "腰围": ("waist", "cm", "num"),
    "臀围": ("hip", "cm", "num"),
    "胸围": ("chest", "cm", "num"),
    "臂围": ("arm", "cm", "num"),
}


def _num(text: str):
    if text is None:
        return None
    s = str(text).strip().replace("％", "%").replace("，", ",")
    m = re.findall(r"-?\d+(?:\.\d+)?", s)
    return [float(x) for x in m] if m else None


def _one(text):
    v = _num(text)
    return v[0] if v else None


def parse_text(text: str) -> dict:
    out = {"store": None, "coach": None, "member": None, "gender": None,
           "age": None, "card": None, "goals": [], "metrics": {}, "warnings": []}

    def grab(label, pattern=r"[:：]\s*([^\n\r]+)"):
        m = re.search(label + pattern, text)
        return m.group(1).strip() if m else None

    store = grab("门店")
    if store:
        m = re.search(r"[（(]([^）)]+)[）)]", store)
        out["store"] = (m.group(1) if m else store).replace("店", "").strip()
    out["coach"] = grab("教练")
    out["member"] = grab("姓名")
    out["gender"] = grab("性别")
    age = grab("年龄")
    out["age"] = _one(age) if age else None
    out["card"] = grab("卡种")
    goals_line = grab("训练目标", r"[:：]?\s*([^\n\r]+)")
    if goals_line:
        out["goals"] = [g for g in ("减脂", "塑形", "增肌", "体态调整", "产后修复") if g in goals_line]
    return out


def parse_table(rows: list) -> dict:
    """rows: [[单元格文本...]]，第一行是表头"""
    metrics, warnings = {}, []
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        label = row[0].strip()
        if label not in FIELDS:
            continue
        key, unit, kind = FIELDS[label]
        before_txt, after_txt, delta_txt = (row + ["", "", ""])[1:4]
        if kind == "date":
            metrics[key] = {"before": before_txt.strip(), "after": after_txt.strip(),
                            "delta": _one(delta_txt), "unit": unit}
            continue
        b, a, d = _num(before_txt), _num(after_txt), _num(delta_txt)
        metrics[key] = {
            "before": b[0] if b and len(b) == 1 else b,
            "after": a[0] if a and len(a) == 1 else a,
            "delta": d[0] if d and len(d) == 1 else d,
            "unit": unit,
        }
    # 一致性校验
    w, fat, bmi = metrics.get("weight", {}), metrics.get("fat", {}), metrics.get("bmi", {})
    if isinstance(w.get("before"), (int, float)) and isinstance(w.get("after"), (int, float)) \
            and isinstance(w.get("delta"), (int, float)):
        if abs((w["before"] - w["after"]) - abs(w["delta"])) > 1.0:
            warnings.append(f"体重差与变化量不符：{w['before']}-{w['after']} vs {w['delta']}")
    h = metrics.get("height", {})
    if isinstance(h.get("before"), (int, float)) and isinstance(w.get("before"), (int, float)) \
            and isinstance(bmi.get("before"), (int, float)) and h["before"] > 0:
        calc = w["before"] / (h["before"] / 100) ** 2
        if abs(calc - bmi["before"]) > 1.0:
            warnings.append(f"BMI 与身高体重推算不符：推算 {calc:.1f}，报告 {bmi['before']}")
    return {"metrics": metrics, "warnings": warnings}


def from_docx(path: Path) -> dict:
    import docx
    d = docx.Document(str(path))
    text = "\n".join(p.text for p in d.paragraphs if p.text.strip())
    rows = []
    for t in d.tables:
        for r in t.rows:
            rows.append([c.text.strip().replace("\n", " ") for c in r.cells])
    info = parse_text(text)
    table = parse_table(rows) if rows else {"metrics": {}, "warnings": ["未见数据表"]}
    info.update(table)
    info.update(ok=bool(info.get("member")), source="docx")
    if not info["metrics"]:
        info["warnings"].append("未解析到指标表")
    return info


def from_pdf(path: Path) -> dict:
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        return {"ok": False, "source": "pdf", "warnings": [f"PDF 解析失败: {e}"]}
    if len(text.strip()) < 80:
        return {"ok": False, "source": "pdf", "needs_ocr": True,
                "warnings": ["PDF 无文本层，需走 OCR（二期）"]}
    info = parse_text(text)
    m = re.search(r"类别[^\n]*\n(.+)", text)
    info.update(metrics={}, warnings=info.get("warnings", []))
    info["ok"] = bool(info.get("member"))
    info["source"] = "pdf"
    info["_text_len"] = len(text)
    return info


def parse(path: Path) -> dict:
    ext = path.suffix.lower()
    if ext == ".docx":
        return from_docx(path)
    if ext == ".pdf":
        return from_pdf(path)
    return {"ok": False, "source": ext.lstrip("."), "warnings": ["不支持的文档类型"]}
