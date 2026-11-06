"""Compatibility entry for the standalone report HTML exporter."""
from scripts.body_report_compare.html import export

if __name__ == "__main__":
    import argparse, json
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--reports", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(export(a.reports, a.out), ensure_ascii=False))
