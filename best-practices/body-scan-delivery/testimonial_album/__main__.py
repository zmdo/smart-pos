import argparse
from pathlib import Path
from .pipeline import run

def main():
    p=argparse.ArgumentParser(description='Render member testimonial album from scored screenshot evidence')
    for name in ('input','evidence','out','font'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--config',type=Path);a=p.parse_args()
    print(run(a.input,a.evidence,a.out,a.font,a.config))

if __name__=='__main__':main()
