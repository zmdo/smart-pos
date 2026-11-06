"""Only data crosses nodes. Consumers never import the producing node."""
import math
import re
from pathlib import Path

from .io import read, save, sha, bind
from .labels import decorate

REPORT_SCHEMA = 'body-report-comparison-v1'
PHASE_SCHEMA = 'body-scan-phase-labels-v1'


def seal(directory, schema, filenames):
    root = Path(directory)
    save(root/'bundle.json', {'schema_version':schema, 'files':{name:sha(root/name) for name in filenames}})


def open_bundle(directory, schema, required, bindings=None):
    root = Path(directory).resolve(); bindings = bindings if bindings is not None else {}
    manifest = read(bind(root/'bundle.json', bindings))
    files = manifest.get('files')
    if manifest.get('schema_version') != schema or not isinstance(files, dict) or set(required)-set(files):
        raise ValueError('unsupported_or_incomplete_bundle')
    for name, expected in files.items():
        path = (root/name).resolve()
        if not path.is_relative_to(root) or not isinstance(expected, str):
            raise ValueError('invalid_bundle_file')
        bind(path, bindings, expected)
    return manifest


def load_reports(directory, bindings=None):
    open_bundle(directory, REPORT_SCHEMA, ('reports.json','inventory.json','index.html'), bindings)
    reports = read(Path(directory)/'reports.json'); seen = set()
    if not isinstance(reports, list):
        raise ValueError('invalid_report_records')
    for row in reports:
        rid = row.get('report_id')
        if not isinstance(rid, str) or not re.fullmatch(r'r\d+', rid) or rid in seen:
            raise ValueError('duplicate_or_invalid_report_id')
        seen.add(rid)
        if not row.get('store','').endswith('店') or row.get('status') not in ('needs_review','verified_transcription'):
            raise ValueError('invalid_report_identity_or_status')
        if row['status'] == 'verified_transcription' and (not row.get('member') or not isinstance(row.get('metrics'),dict)):
            raise ValueError('invalid_verified_report')
    return reports


def load_labels(directory):
    root = Path(directory).resolve(); bindings = {}
    open_bundle(root, PHASE_SCHEMA, ('labels.json','inputs.json','report-link.json'), bindings)
    rows = read(root/'labels.json'); inputs = read(root/'inputs.json')
    photos = inputs['photos']; seen = set(); identities = {}
    if not isinstance(rows, list) or not rows:
        raise ValueError('empty_phase_labels')
    for row in rows:
        aid = row.get('asset_id'); gid = row.get('group_id')
        if (not isinstance(aid,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',aid) or aid in seen
                or not isinstance(gid,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',gid)
                or not row.get('store','').endswith('店') or not row.get('member')
                or row.get('view') not in ('front','back','side','side_left','side_right')
                or row.get('phase') not in ('before','after')
                or row.get('label_kind') not in ('human','rule','inferred','pending')):
            raise ValueError('incomplete_or_invalid_phase_labels')
        seen.add(aid)
        identity = (row['store'],row['member'])
        if identities.setdefault(gid,identity) != identity:
            raise ValueError('group_identity_mismatch')
        score = row.get('confidence')
        if score is not None and (type(score) not in (float,int) or not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('invalid_phase_confidence')
        expected = decorate(dict(row))
        if row.get('label') != expected['label'] or row.get('requires_review') != expected['requires_review']:
            raise ValueError('phase_review_marker_mismatch')
    if seen != set(photos):
        raise ValueError('phase_photo_coverage_mismatch')
    for path, expected in inputs['bindings'].items():
        bind(path, bindings, expected)
    for path in photos.values():
        if str(Path(path).resolve()) not in inputs['bindings']:
            raise ValueError('unbound_display_photo')
    return rows, photos, bindings, read(root/'report-link.json')
