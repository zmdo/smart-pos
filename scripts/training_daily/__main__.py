import argparse
from pathlib import Path
from .pipeline import run

def main():
    p=argparse.ArgumentParser(description='Render training photos from approved action evidence; no model calls')
    for name in ('input','evidence','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--config',type=Path);args=p.parse_args()
    print(run(args.input,args.evidence,args.out,args.config))

if __name__=='__main__':main()
