import argparse
from pathlib import Path

from .pipeline import create,correct,read

parser=argparse.ArgumentParser(description='生成带推断/待审标记的体测成品，并支持人工修正后重新生成')
commands=parser.add_subparsers(dest='command',required=True)
new=commands.add_parser('create')
new.add_argument('--phase',type=Path,required=True);new.add_argument('--out',type=Path,required=True)
new.add_argument('--font',type=Path,required=True)
new.add_argument('--reports',type=Path)
new.add_argument('--presentation',type=Path,help='品牌、地址、称谓和页脚指标配置 JSON')
new.add_argument('--reuse-renders',type=Path,help='已有 result.json 版本目录，仅复用依赖哈希完全相同的成品')
review=commands.add_parser('review');review.add_argument('--delivery',type=Path,required=True);review.add_argument('--request',type=Path,required=True)
args=parser.parse_args()
if args.command=='create':
    result=create(args.phase,args.out,args.font,args.reports,args.presentation,args.reuse_renders)
else:result=correct(args.delivery,read(args.request))
print({'delivery_id':result['delivery_id'],'revision':result['revision'],**result['counts']})
