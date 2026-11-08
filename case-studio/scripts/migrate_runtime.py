"""Offline migration/restore; stop the website before running this command."""
import argparse, os, sqlite3
from contextlib import closing
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--source',type=Path,required=True)
parser.add_argument('--destination',type=Path,required=True)
args=parser.parse_args()
source=args.source.resolve();destination=args.destination.resolve()
if not source.is_file() or destination.exists() or source==destination:
    raise SystemExit('Source must exist; destination must be a new file')
destination.parent.mkdir(parents=True,exist_ok=True)
temp=destination.with_suffix('.migration.sqlite3')
if temp.exists():raise SystemExit('A previous migration temp file exists; inspect it first')
with closing(sqlite3.connect('file:'+str(source)+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(temp)) as dst:
    src.backup(dst)
    if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise SystemExit('Integrity check failed')
    tables=[r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        name='"'+table.replace('"','""')+'"'
        assert src.execute('SELECT count(*) FROM '+name).fetchone()==dst.execute('SELECT count(*) FROM '+name).fetchone()
        # Compare full contents, including sessions, version payloads, and media bindings.
        assert src.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()==dst.execute('SELECT * FROM '+name+' ORDER BY rowid').fetchall()
    dst.execute('PRAGMA journal_mode=WAL')
    dst.execute('PRAGMA wal_checkpoint(TRUNCATE)')
os.chmod(temp,0o600);os.replace(temp,destination)
print('Migration verified:',len(tables),'tables; source retained')
