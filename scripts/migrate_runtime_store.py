"""Offline, non-destructive copy into an empty Linux runtime volume.

Stop API and worker first. Mount original read-only at /source, empty volume at
/destination, and results at /evidence. Never point this script at a live writer.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4*1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    source, destination = Path('/source'), Path('/destination')
    if not source.is_dir() or not destination.is_dir() or any(destination.iterdir()):
        raise RuntimeError('migration_requires_readonly_source_and_empty_destination')
    records = []
    for index, original in enumerate(sorted(source.rglob('*'))):
        if original.is_symlink():
            raise RuntimeError('unexpected_source_symlink:' + str(original))
        target = destination / original.relative_to(source)
        if original.is_dir():
            target.mkdir(exist_ok=True)
            continue
        shutil.copy2(original, target)
        checksum = digest(original)
        if digest(target) != checksum:
            raise RuntimeError('copy_digest_mismatch:' + str(original))
        records.append(dict(path=str(original.relative_to(source)), bytes=original.stat().st_size, sha256=checksum))
        if index % 100 == 0:
            print(json.dumps(dict(copied=len(records))), flush=True)
    checks = {}
    for target in sorted(destination.rglob('*.db')):
        if target.stat().st_size == 0:
            continue
        conn = sqlite3.connect(target)
        try:
            result = conn.execute('PRAGMA integrity_check').fetchall()
            if result != [('ok',)]:
                raise RuntimeError('integrity_failed:' + str(target) + repr(result))
            checks[str(target.relative_to(destination))] = 'ok'
        finally:
            conn.close()
    report = dict(files=len(records), total_bytes=sum(r['bytes'] for r in records),
                  sha256_verified=records, databases=checks, source_preserved=True)
    Path('/evidence/runtime-volume-migration.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k!='sha256_verified'}),flush=True)


if __name__ == '__main__':
    main()
