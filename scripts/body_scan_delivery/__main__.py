import argparse
from pathlib import Path

from .pipeline import create,correct,read

parser=argparse.ArgumentParser(description='生成带推断/待审标记的体测成品，并支持人工修正后重新生成')
commands=parser.add_subparsers(dest='command',required=True)
new=commands.add_parser('create')
new.add_argument('--phase',type=Path,required=True);new.add_argument('--out',type=Path,required=True)
new.add_argument('--font',type=Path,required=True);new.add_argument('--settings',type=Path)
new.add_argument('--cache',type=Path);new.add_argument('--provider',choices=['qwen','deepseek'],default='qwen')
review=commands.add_parser('review');review.add_argument('--delivery',type=Path,required=True);review.add_argument('--request',type=Path,required=True)
args=parser.parse_args()
if args.command=='create':
    client=None
    if args.settings:
        if not args.cache:parser.error('--settings requires --cache')
        from scripts.body_scan_full_eval.client import MeasuredClient
        client=MeasuredClient(args.settings,args.cache,args.provider)
    result=create(args.phase,args.out,args.font,client)
else:result=correct(args.delivery,read(args.request))
print({'delivery_id':result['delivery_id'],'revision':result['revision'],**result['counts']})
