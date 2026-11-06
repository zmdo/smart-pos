import argparse
from pathlib import Path

from .pipeline import run

parser = argparse.ArgumentParser(description='独立实验：按部位比较 + 训练报告辅助，保留无法判定的照片')
parser.add_argument('--input', type=Path, required=True)
parser.add_argument('--override', type=Path, action='append', default=[])
parser.add_argument('--baseline', type=Path)
parser.add_argument('--reports', type=Path, help='独立报告节点的 bundle 目录；不接受原始 PDF/DOCX 目录')
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--settings', type=Path, required=True)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--provider', choices=['qwen','deepseek'], default='qwen')
parser.add_argument('--member', action='append', default=[])
parser.add_argument('--workers', type=int, choices=range(1,5), default=3)
parser.add_argument('--controls', action='store_true')
args = parser.parse_args()
print(run(args))
