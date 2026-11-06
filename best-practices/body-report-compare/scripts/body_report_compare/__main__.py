import argparse
from pathlib import Path
from scripts.body_scan_contracts.client import MeasuredClient
from .pipeline import run

p = argparse.ArgumentParser(description='独立体检报告提取、核验、前后对比 JSON 和 HTML；不需要照片')
p.add_argument('--input',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--settings',type=Path)
p.add_argument('--cache',type=Path)
p.add_argument('--provider',choices=['qwen','deepseek'],default='qwen')
p.add_argument('--reuse',type=Path,help='复用旧转录答复，但仍重新与原文件核验')
a = p.parse_args()
if bool(a.settings) != bool(a.cache): p.error('--settings and --cache must be supplied together')
print(run(a.input,a.out,MeasuredClient(a.settings,a.cache,a.provider) if a.settings else None,a.reuse))
