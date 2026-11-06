import argparse
from pathlib import Path
from .pipeline import run

p=argparse.ArgumentParser(description='会员案例封面：固定取景、报告文案、离线 HTML 预览')
p.add_argument('--delivery',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--config',type=Path,help='可选标题、正文、教练及地址覆盖配置')
a=p.parse_args()
print(run(a.delivery,a.out,a.config)['counts'])
