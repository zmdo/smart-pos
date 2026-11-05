"""Run the unchanged session policy on a shared full-dataset display set."""
import argparse
from pathlib import Path

from scripts.body_scan.pipeline import save_json
from scripts.body_scan_phase_sessions.evidence import SessionEvidence
from scripts.body_scan_phase_sessions.pipeline import run
from scripts.body_scan_phase_sessions.preview import preview
from .client import MeasuredClient


def evaluate(directory, out, settings, provider, cache, workers=3):
    client = MeasuredClient(settings, cache, provider)
    evidence = SessionEvidence(cache)
    evidence.ask = client.ask
    counts = run(directory, out, evidence=evidence, workers=workers)
    save_json(Path(out)/'evaluation.json', {'provider': provider, 'requested_model': client.cfg['model'],
        'cache': str(Path(cache).resolve()), 'same_policy': 'body-scan-phase-sessions-v2',
        'scope': 'All eligible full-dataset standardized images, with upstream exclusions separately recorded'})
    preview(out)
    page = Path(out)/'index.html'
    page.write_text(page.read_text(encoding='utf-8').replace('当前验证子集，非完整上传包。',
        '完整素材盘点后通过上游处理的全部图片；被过滤和待复核项见全量覆盖清单。'), encoding='utf-8')
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--settings', type=Path, required=True); parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--provider', choices=['deepseek', 'qwen'], required=True)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    evaluate(args.input, args.out, args.settings, args.provider, args.cache, args.workers)
