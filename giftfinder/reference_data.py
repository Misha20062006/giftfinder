"""Versioned public data updates. Downloaded content is validated JSON, never code."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

from .network import request
from .monochrome import COLORS

BASE_URL = 'https://raw.githubusercontent.com/Misha20062006/giftfinder/main/giftfinder/'
FILES = ('catalog_full.json', 'themes_curated.json', 'monochrome_pairs.json')
THEME_KEYS = {row['key'] for row in json.loads((Path(__file__).parent/'themes_curated.json').read_text(encoding='utf-8'))['themes']}


def names(rows):
    if not isinstance(rows, list) or any(not isinstance(r, dict) or not isinstance(r.get('name'), str) or not r['name'].strip() for r in rows):
        raise ValueError('Invalid trait rows')
    return rows


def validate_catalog(payload):
    if not isinstance(payload, dict): raise ValueError('Invalid catalog')
    collections = payload.get('collections')
    if not isinstance(collections, list) or not collections or any(not isinstance(c, str) or not c.strip() for c in collections):
        raise ValueError('Invalid collections')
    names(payload.get('backdrops'))
    for backdrop in payload['backdrops']:
        if 'hex' in backdrop and not isinstance(backdrop['hex'],dict): raise ValueError('Invalid backdrop palette')
    traits = payload.get('traits')
    if not isinstance(traits, dict): raise ValueError('Invalid traits')
    for collection, rows in traits.items():
        if not isinstance(collection, str) or not isinstance(rows, dict): raise ValueError('Invalid collection traits')
        names(rows.get('models')); names(rows.get('symbols'))
    return payload


def merge_catalog(old, incoming):
    traits = dict(old.get('traits', {}))
    for collection, row in incoming.get('traits', {}).items():
        previous = traits.get(collection, {})
        traits[collection] = {kind:list({r['name']:r for r in previous.get(kind, []) + row.get(kind, [])}.values()) for kind in ('models','symbols')}
    backdrops = {r['name']:r for r in old.get('backdrops', []) + incoming.get('backdrops', [])}
    return {**old, **incoming, 'collections':sorted(set(old.get('collections', [])) | set(incoming.get('collections', []))),
            'traits':traits, 'backdrops':list(backdrops.values())}


def validate_themes(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('themes'), list) or not payload['themes']:
        raise ValueError('Invalid themes')
    seen = set()
    for row in payload['themes']:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or row['key'] in seen:
            raise ValueError('Invalid theme')
        seen.add(row['key'])
        if any(key in row and not isinstance(row[key],str) for key in ('title','subtitle')):
            raise ValueError('Invalid theme label')
        if 'color' in row and (not isinstance(row['color'],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',row['color'])):
            raise ValueError('Invalid theme colour')
        if not isinstance(row.get('members'), list): raise ValueError('Invalid theme members')
        for pair in row['members']:
            if not isinstance(pair, list) or len(pair) != 2 or any(not isinstance(v, str) or not v.strip() for v in pair):
                raise ValueError('Invalid model pair')
    if not THEME_KEYS <= seen: raise ValueError('Incomplete theme update')
    return payload


def validate_monochrome(payload):
    if not isinstance(payload, dict) or payload.get('schema') != 1 or not isinstance(payload.get('models'), list):
        raise ValueError('Invalid monochrome data')
    for row in payload['models']:
        if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('collection','model')):
            raise ValueError('Invalid monochrome model')
        if row.get('family') not in COLORS or not isinstance(row.get('backdrops'), list) or not row['backdrops'] or any(not isinstance(b, str) or not b.strip() for b in row['backdrops']):
            raise ValueError('Invalid monochrome backdrops')
    return payload


class ReferenceStore:
    def __init__(self, directory):
        self.path = Path(directory) / 'reference-data.json'
        self.bundle = None
        self.payloads = None
        try:
            self.minimum_updated_at = json.loads((Path(__file__).parent/'catalog_updates.json').read_text(encoding='utf-8')).get('updated_at',0)
        except (OSError, ValueError, AttributeError):
            self.minimum_updated_at = 0
        try:
            bundle = json.loads(self.path.read_text(encoding='utf-8'))
            self.payloads = self.decode(bundle)
            if bundle['manifest'].get('updated_at',0) < self.minimum_updated_at:
                self.payloads = None
                return
            self.bundle = bundle
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @staticmethod
    def decode(bundle):
        if not isinstance(bundle,dict) or not isinstance(bundle.get('manifest'),dict) or not isinstance(bundle.get('files'),dict):
            raise ValueError('Invalid reference bundle')
        manifest = bundle['manifest']
        if manifest.get('schema') != 1 or not isinstance(manifest.get('files'),dict) or set(manifest['files']) != set(FILES): raise ValueError('Invalid manifest')
        timestamp = manifest.get('updated_at',0)
        if not isinstance(timestamp,(int,float)) or not math.isfinite(timestamp) or timestamp < 0: raise ValueError('Invalid reference date')
        payloads = {}
        for name, validate in zip(FILES, (validate_catalog, validate_themes, validate_monochrome)):
            content = bundle['files'][name]
            if not isinstance(content,str): raise ValueError('Invalid reference file')
            if hashlib.sha256(content.encode('utf-8')).hexdigest() != manifest['files'][name]:
                raise ValueError('Reference checksum mismatch')
            payloads[name] = validate(json.loads(content))
        return payloads

    def refresh(self):
        manifest = request('GET', BASE_URL + 'catalog_updates.json').json()
        if self.bundle and manifest == self.bundle['manifest']: return self.payloads
        if not isinstance(manifest, dict) or manifest.get('schema') != 1 or set(manifest.get('files', {})) != set(FILES):
            raise ValueError('Invalid reference manifest')
        if manifest.get('updated_at',0) < max(self.minimum_updated_at, self.bundle['manifest'].get('updated_at',0) if self.bundle else 0):
            raise ValueError('Outdated reference manifest')
        # Fixed filenames stay on the project's public data endpoint.
        bundle = {'manifest':manifest, 'files':{name:request('GET', BASE_URL + name).content.decode('utf-8') for name in FILES}}
        payloads = self.decode(bundle)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.path)
        self.bundle, self.payloads = bundle, payloads
        return payloads
