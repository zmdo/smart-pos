import argparse
from pathlib import Path
from .pipeline import run


def main():
    parser=argparse.ArgumentParser(description='Export classified lifestyle photos unchanged; no models or stage labels')
    for name in ('input','audit','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    print(run(args.input,args.audit,args.out))


if __name__=='__main__':main()
