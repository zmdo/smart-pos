"""Adapt the authoritative original-first table bundle to the phase node contract."""

import math, html
from datetime import date
from .common import read, save, sha


def build(tables, out):
    out.mkdir(parents=True, exist_ok=False)
    cases = read(tables / "tables.json")
    records = []
    for i, c in enumerate(cases, 1):
        if c.get("source_policy") != "original_measurements_first_summary_fills_gaps":
            raise ValueError("报告必须使用原始数据优先策略")
        pair = c.get("pair") or {}
        metrics = {}
        for row in c["rows"]:
            key = {"fat_percent": "fat", "skeletal_muscle": "muscle"}.get(
                row.get("key"), row.get("key")
            )
            if not key or key == "date":
                continue
            try:
                a, b = float(row["before"]), float(row["after"])
                if not all(math.isfinite(v) for v in (a, b)):
                    continue
            except (TypeError, ValueError):
                continue
            metrics[key] = dict(
                usable=True,
                row_label=row["type"],
                before=row["before"],
                after=row["after"],
                before_values=[a],
                after_values=[b],
                computed_delta=[round(b - a, 4)],
                unit=row["unit"],
                source_row=row.get("sources"),
                warnings=row.get("warnings", []),
            )
        dt = next((r for r in c["rows"] if r.get("key") == "date"), {})
        before = pair.get("before_date") or dt.get("before")
        after = pair.get("after_date") or dt.get("after")
        issue = None
        days = None
        try:
            d1, d2 = date.fromisoformat(before), date.fromisoformat(after)
            if not date(2000, 1, 1) <= d1 <= d2 <= date.fromisoformat(c["as_of"]):
                raise ValueError()
            days = (d2 - d1).days
        except (ValueError, TypeError):
            issue = "report_dates_unverified"
        records.append(
            dict(
                report_id=f"r{i:03d}",
                store=c["store"],
                member=c["member"],
                printed_member=c.get("display_member"),
                status="verified_transcription" if metrics else "needs_review",
                metrics=metrics,
                source=str(tables / "tables.json"),
                source_sha256=sha(tables / "tables.json"),
                source_ids=c.get("source_ids", []),
                source_policy=c["source_policy"],
                columns={"before": "初始数据（训练前）", "after": "阶段数据（训练后）"},
                before_date=before,
                after_date=after,
                stated_days=days,
                date_issue=issue,
                checked_goals=[],
                warnings=c.get("warnings", []),
                table_case_id=c["case_id"],
            )
        )
    save(out / "reports.json", records)
    save(
        out / "inventory.json",
        [
            {
                "report_id": r["report_id"],
                "store": r["store"],
                "member": r["member"],
                "status": r["status"],
                "source": r["source"],
            }
            for r in records
        ],
    )
    save(
        out / "sources.json",
        {
            str(tables / name): sha(tables / name)
            for name in ("bundle.json", "tables.json", "records.json")
        },
    )
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><h1>统一报告数据</h1>'
        + "".join(
            "<p>" + html.escape(r["store"] + " / " + r["member"]) + "</p>"
            for r in records
        ),
        encoding="utf-8",
    )
    save(
        out / "bundle.json",
        {
            "schema_version": "body-report-comparison-v1",
            "files": {
                name: sha(out / name)
                for name in (
                    "reports.json",
                    "inventory.json",
                    "index.html",
                    "sources.json",
                )
            },
        },
    )
    return out
