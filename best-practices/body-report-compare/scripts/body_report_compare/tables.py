"""Independent image/document five-column table CLI; old report bundle API unchanged."""
import argparse
from datetime import date
from .table_data import today_cn
from pathlib import Path
from scripts.body_scan_contracts.client import MeasuredClient
from .table_pipeline import run

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('input','audit','out','settings','cache'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--workers',type=int,choices=range(1,5),default=3)
    p.add_argument('--as-of',type=date.fromisoformat,default=today_cn(),help='日期校验上限，默认上海时区今天')
    a=p.parse_args()
    if a.as_of>today_cn():p.error('--as-of cannot exceed today')
    client=MeasuredClient(a.settings,a.cache,'qwen',max_image_side=2200,max_tokens=6000)
    print(run(a.input,a.audit,a.out,client,a.workers,a.as_of))
if __name__=='__main__':main()
