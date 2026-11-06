import argparse
from pathlib import Path
from .pipeline import run

p=argparse.ArgumentParser(description='会员案例封面：固定取景、报告文案、离线 HTML 预览')
p.add_argument('--delivery',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--config',type=Path,help='可选标题、正文、教练及地址覆盖配置')
p.add_argument('--cover-frames',type=Path,help='同组展示最佳实践输出的封面双图目录')
p.add_argument('--legacy-display-crop',action='store_true',help='仅用于旧版回归对照')
a=p.parse_args()
print(run(a.delivery,a.out,a.config,a.cover_frames,a.legacy_display_crop)['counts'])
