import argparse
from pathlib import Path
from .pipeline import run

def main():
    p = argparse.ArgumentParser(description='封面专用正面双图节点：复用阶段标签及校正，只等比取景')
    p.add_argument('--request', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--width', type=int, default=500)
    p.add_argument('--height', type=int, default=478)
    p.add_argument('--max-torso-heights', type=float, default=2.8)
    a = p.parse_args()
    r = run(a.request, a.out, (a.width, a.height), a.max_torso_heights)
    print({'pairs': len(r['cases']), 'gaps': len(r['gaps']), 'model_requests': 0})


if __name__ == '__main__':
    main()
