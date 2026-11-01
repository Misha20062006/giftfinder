"""Refresh public gift metadata and publish checksums for the reviewed data files."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from giftfinder.catalogue import Catalog
from giftfinder.reference_data import FILES, ReferenceStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='Isolated working directory outside user profiles')
    parser.add_argument('--refresh', action='store_true', help='Read the current public metadata source')
    args = parser.parse_args()
    directory = ROOT/'giftfinder'
    if args.refresh:
        catalog = Catalog(args.work)
        catalog.refresh(print, include_references=False)
        if not catalog.data.get('updated_at') or catalog.data.get('failures'):
            raise SystemExit('Public metadata refresh was incomplete; bundled data was not changed')
        (directory/'catalog_full.json').write_text(json.dumps(catalog.data, ensure_ascii=False, separators=(',',':'))+'\n', encoding='utf-8')
    contents = {name:(directory/name).read_text(encoding='utf-8') for name in FILES}
    manifest = {'schema':1, 'updated_at':int(time.time()), 'files':{name:hashlib.sha256(content.encode('utf-8')).hexdigest() for name,content in contents.items()}}
    ReferenceStore.decode({'manifest':manifest, 'files':contents})
    (directory/'catalog_updates.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    print('Validated public catalog, reviewed themes and monochrome data manifest')


if __name__ == '__main__': main()
