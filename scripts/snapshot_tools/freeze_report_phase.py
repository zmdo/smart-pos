"""Freeze the actual Python import closure; never resolve imports into sibling nodes."""
import argparse
import ast
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def module_file(name):
    p=ROOT/Path(*name.split('.'))
    for candidate in (p.with_suffix('.py'),p/'__init__.py'):
        if candidate.is_file():return candidate


def closure(seeds):
    found=set();todo=list(seeds)
    while todo:
        path=todo.pop()
        if path in found:continue
        found.add(path)
        rel=path.relative_to(ROOT).with_suffix('');parts=list(rel.parts)
        package=parts[:-1]
        for node in ast.walk(ast.parse(path.read_text())):
            modules=[]
            if isinstance(node,ast.Import):modules=[a.name for a in node.names]
            elif isinstance(node,ast.ImportFrom):
                prefix=package[:len(package)-node.level+1] if node.level else []
                if node.module:prefix+=node.module.split('.')
                base='.'.join(prefix);modules=[base]+[base+'.'+a.name for a in node.names]
            for name in modules:
                if not name.startswith('scripts.'):continue
                file=module_file(name)
                if file:todo.append(file)
        for i in range(2,len(parts)):
            init=ROOT/Path(*parts[:i])/'__init__.py'
            if init.is_file():todo.append(init)
    return found


def freeze(name,package,commit):
    target=ROOT/'best-practices'/name;target.mkdir(exist_ok=True)
    seeds=list((ROOT/'scripts'/package).rglob('*.py'))
    seeds+=list((ROOT/'scripts/body_scan_contracts/tests').glob('*.py'))
    if package=='body_scan_phase_classification':seeds.append(ROOT/'scripts/body_scan_phase_regions/verify.py')
    files=closure(seeds)
    forbidden=('body_scan_delivery', 'body_report_compare') if package=='body_scan_phase_classification' else ('body_scan_phase_regions','body_scan_phase_classification','body_scan_delivery')
    if any(any(f'/{word}/' in str(path) for word in forbidden) for path in files):raise ValueError('cross_node_import_dependency')
    for source in sorted(files):
        rel=source.relative_to(ROOT);data=subprocess.check_output(['git','show',commit+':'+str(rel)],cwd=ROOT)
        if hashlib.sha256(data).hexdigest()!=digest(source):raise ValueError('source_not_at_pinned_commit: '+str(rel))
        dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
    shutil.copyfile(ROOT/'best-practices/body-scan-group-display-v3/snapshot.py',target/'snapshot.py')
    shutil.copyfile(ROOT/'best-practices/body-scan-group-display-v3/scripts/__init__.py',target/'scripts/__init__.py')
    launcher='''"""Isolated entry point for the frozen node."""
import os
import runpy
import sys
from pathlib import Path
from snapshot import verify_integrity
root=Path(__file__).resolve().parent
verify_integrity(root)
'''
    if package=='body_report_compare':
        launcher+='''deps=Path(os.environ.get('CASE_REPORT_DEPS','/root/apps/phase-evidence-deps'))
if deps.is_dir():sys.path.insert(1,str(deps))
'''
    launcher+=f"runpy.run_module('scripts.{package}',run_name='__main__')\n"
    (target/'launch.py').write_text(launcher)
    (target/'run.sh').write_text('''#!/bin/bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
unset PYTHONPATH
export PYTHONNOUSERSITE=1 PYTHONUTF8=1
CASE_PYTHON=${CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}
exec "$CASE_PYTHON" -u launch.py "$@"
''');(target/'run.sh').chmod(0o755)
    (target/'run_tests.sh').write_text(f'''#!/bin/bash
set -euo pipefail
cd "$(dirname "${{BASH_SOURCE[0]}}")"
unset PYTHONPATH
export PYTHONNOUSERSITE=1
CASE_PYTHON=${{CASE_PYTHON:-/root/apps/non-grid-calibration/.venv/bin/python}}
"$CASE_PYTHON" -m unittest discover -s scripts/body_scan_contracts/tests
"$CASE_PYTHON" -m unittest discover -s scripts/{package}/tests
''');(target/'run_tests.sh').chmod(0o755)
    readme=(ROOT/'scripts'/package/'README.md').read_text().replace('../../docs/','../../docs/')
    readme+='\n## 冻结入口\n\n从任意目录执行本目录 `run.sh`，参数与开发模块相同。启动时核验所有代码和文档 SHA；清空 PYTHONPATH，不回退到开发树或其他节点。`run_tests.sh` 运行独立契约与节点测试。模型配置、素材、字体和缓存仍使用显式外部路径，私钥不归档。来源提交和文件指纹见 `manifest.json`，远程验收见 `validation.json`。\n'
    (target/'README.md').write_text(readme)
    entries=[]
    for path in sorted(target.rglob('*')):
        if not path.is_file() or path.name in ('manifest.json','validation.json') or '__pycache__' in path.parts:continue
        rel=path.relative_to(target).as_posix();entry={'path':rel,'sha256':digest(path)}
        if ROOT/rel in files:entry.update(source=rel,source_commit=commit,source_sha256=digest(ROOT/rel))
        entries.append(entry)
    manifest={'version':name+'-v1','authority':'user-approved independent processing node',
              'source_commit':commit,'entrypoint':'run.sh','files':entries,
              'dependencies':'self-contained verified Python import closure; no sibling best-practice or development fallback'}
    (target/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(name,len(files),'source modules')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source-commit',required=True);a=p.parse_args()
    freeze('body-report-compare','body_report_compare',a.source_commit)
    freeze('body-scan-phase-classification','body_scan_phase_classification',a.source_commit)
