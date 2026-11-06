"""Complete before/after labels, independent of product templates and rendering."""
from collections import Counter
from pathlib import Path

from scripts.body_scan_contracts.io import read, save, bind, sha
from scripts.body_scan_contracts.bundles import seal, load_labels, load_reports
from scripts.body_scan_contracts.labels import decorate
from . import VERSION
from .assignment import assign, required_ranking
from .ranking import rank
from .inputs import load_phase


def finalize(analysis, out, client=None, reports=None, corrections=None):
    analysis = Path(analysis).resolve(); out = Path(out).resolve()
    rows, groups, photos, bindings = load_phase(analysis)
    # Reusing legacy analyses is allowed only when their report data agrees
    # with the supplied bundle. A different report requires fresh analysis.
    old_reports = read(bind(analysis/'reports/reports.json',bindings))
    report_link = {'path':None,'sha256':None}
    if reports:
        reports = Path(reports).resolve()
        data = load_reports(reports,bindings)
        by_id = {r['report_id']:r for r in data}
        for old in old_reports:
            new = by_id.get(old['report_id'])
            keys = ('store','member','source_sha256','status','metrics','columns','before_date','after_date','date_issue')
            if not new or any(old.get(k) != new.get(k) for k in keys):
                raise ValueError('report_changed_rerun_visual_analysis')
        matched = {(r['store'],r['member']) for r in rows}
        if {r['report_id'] for r in data if (r['store'],r.get('member')) in matched} != {r['report_id'] for r in old_reports}:
            raise ValueError('report_coverage_changed_rerun_visual_analysis')
        report_link = {'path':str(reports),'sha256':sha(reports/'bundle.json')}
    elif old_reports:
        raise ValueError('analysis_requires_its_report_bundle')
    analysis_link = analysis/'report-link.json'
    if analysis_link.exists() and read(bind(analysis_link,bindings)) != report_link:
        raise ValueError('analysis_report_bundle_mismatch')
    out.mkdir(parents=True,exist_ok=False); assigned = []
    for group in groups:
        original = [r for r in rows if r['asset_id'] in group['asset_ids']]
        required = required_ranking(group,original)
        scores, audit = rank(client,original,required) if required else ({},{})
        labels, assignment = assign(group,original,scores)
        assigned.extend(labels)
        save(out/'audits'/(group['group_id']+'.json'),{'required_fallback_ids':required,
             'scores':scores,'ranking_audit':audit,'assignment':assignment})
        print('labels',group['member'],dict(Counter(r['label_kind'] for r in labels)),flush=True)
    assigned.sort(key=lambda r:r['asset_id'])
    if corrections:
        changes = read(bind(corrections,bindings)); lookup = {r['asset_id']:r for r in assigned}; seen = set()
        if not isinstance(changes,list): raise ValueError('invalid_confirmed_labels')
        for change in changes:
            aid = change.get('asset_id'); row = lookup.get(aid)
            if not row or aid in seen or change.get('source_sha256') != row['source_sha256'] or change.get('phase') not in ('before','after') or change.get('confirm') is not True:
                raise ValueError('unbound_or_unconfirmed_human_label')
            seen.add(aid)
            row.update(phase=change['phase'],label_kind='human',assignment_reason='explicit_user_review',
                       confidence=None,review_flags=[],human_review=change)
            decorate(row)
    save(out/'labels.json',assigned)
    save(out/'inputs.json',{'photos':photos,'bindings':bindings,'analysis':str(analysis)})
    save(out/'report-link.json',report_link)
    save(out/'config.json',{'version':VERSION,'analysis':str(analysis),'product_generation':False})
    counts = {'images':len(assigned),'members':len(groups),'label_kinds':dict(Counter(r['label_kind'] for r in assigned)),
              'requires_review':sum(r['requires_review'] for r in assigned)}
    save(out/'counts.json',counts)
    seal(out,VERSION,('labels.json','inputs.json','report-link.json'))
    load_labels(out)
    return counts


def run(args):
    from scripts.body_scan_phase_regions.pipeline import run as analyze
    from scripts.body_scan_contracts.client import MeasuredClient
    from argparse import Namespace
    root = args.out.resolve(); root.mkdir(parents=True,exist_ok=False)
    options = {**vars(args),'out':root/'analysis'}
    analyze(Namespace(**options))
    return finalize(root/'analysis',root/'classification',MeasuredClient(args.settings,args.cache,args.provider),
                    args.reports,args.corrections)
