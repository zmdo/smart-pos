import argparse
from pathlib import Path
from .pipeline import finalize, run

p = argparse.ArgumentParser(description='独立训练阶段分类；输出所有照片标签和待审信息，不生成成品')
commands = p.add_subparsers(dest='command',required=True)
new = commands.add_parser('run')
new.add_argument('--input',type=Path,required=True)
new.add_argument('--override',type=Path,action='append',default=[])
new.add_argument('--baseline',type=Path)
new.add_argument('--member',action='append',default=[])
new.add_argument('--workers',type=int,choices=range(1,5),default=3)
new.add_argument('--controls',action='store_true')
final = commands.add_parser('finalize',help='为已完成的视觉分析补齐标签；不重复视觉分析')
final.add_argument('--analysis',type=Path,required=True)
for sub in (new,final):
    sub.add_argument('--out',type=Path,required=True)
    sub.add_argument('--reports',type=Path,help='体检表对比 bundle；没有报告可省略')
    sub.add_argument('--corrections',type=Path,help='包含素材源哈希和 confirm=true 的人工阶段 JSON 列表')
    sub.add_argument('--settings',type=Path,required=sub is new)
    sub.add_argument('--cache',type=Path,required=sub is new)
    sub.add_argument('--provider',choices=['qwen','deepseek'],default='qwen')
a = p.parse_args()
if bool(a.settings) != bool(a.cache): p.error('--settings and --cache must be supplied together')
if a.command == 'run':
    print(run(a))
else:
    from scripts.body_scan_contracts.client import MeasuredClient
    client = MeasuredClient(a.settings,a.cache,a.provider) if a.settings else None
    print(finalize(a.analysis,a.out,client,a.reports,a.corrections))
