from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from urllib.parse import quote

from .i18n import tr, theme_name
from .core import SearchQuery, compact, norm
from . import monochrome
from .network import request, error_note

# Membership is an explicit, visually reviewed allow-list. Keyword rules above
# are research aids only and never add an item to a shipped theme.
_curated = json.loads((Path(__file__).parent/'themes_curated.json').read_text(encoding='utf-8'))
_aliases = {'minecraft':('minecraft','майнкрафт'), 'cheese':('сыр','сырные','cheese'),
            'watermelon':('арбуз','арбузные','watermelon'), 'strawberry':('клубника','клубничные','strawberry'),
            'pumpkin':('тыквы','pumpkin'), 'bee':('пчёлы','пчелы','мёд','мед','honey'),
            'sakura':('сакура','sakura'), 'snowman':('снеговики','snowman'),
            'skeleton':('кости','скелеты','skeleton'), 'rainbow':('радужные','радуга','rainbow')}
THEMES = {row['key']:{**row,'aliases':_aliases.get(row['key'],())} for row in _curated['themes']}


def query_from_dict(data):
    fields = {k:v for k,v in data.items() if k in SearchQuery.__dataclass_fields__}
    for key in ('models','backdrops','symbols','markets','mono_colors'):
        if key in fields:
            fields[key] = tuple(fields[key])
    fields['targets'] = tuple(tuple(x) for x in fields.get('targets', ()))
    return SearchQuery(**fields)


class Catalog:
    def __init__(self, directory: Path, seed: Path | None = None):
        self.directory = directory
        self.path = directory / 'catalog.json'
        self.full_path = directory / 'catalog-v2.json'
        self.note = ''
        self.lock = threading.RLock()
        self.data = {'collections': [], 'backdrops': [], 'traits': {}}
        source = seed or Path(__file__).parent / 'catalog_full.json'
        if source.name == 'catalog_seed.json' and source.with_name('catalog_full.json').exists():
            source = source.with_name('catalog_full.json')
        for file in (source, self.path, self.full_path):
            try:
                payload = json.loads(file.read_text(encoding='utf-8'))
                if not isinstance(payload, dict):
                    continue
                if file == self.path:
                    # v0.1's small catalog does not erase the bundled trait index.
                    self.data['collections'] = sorted(set(self.data['collections']) | set(payload.get('collections',[])),key=norm)
                    backgrounds = {r['name']:r for r in payload.get('backdrops',[]) if isinstance(r,dict) and r.get('name')}
                    backgrounds.update({r['name']:r for r in self.data['backdrops']})
                    self.data['backdrops'] = list(backgrounds.values())
                else:
                    self.data.update(payload)
            except (OSError, ValueError):
                continue
        self.reindex()

    def reindex(self):
        self.model_rows = []
        self.symbol_rows = []
        self.themes = {key: {**value, 'members': []} for key,value in THEMES.items()}
        reviewed = {key:{(compact(c),norm(m)) for c,m in row['members']} for key,row in THEMES.items()}
        for collection in sorted(self.data.get('traits', {}), key=norm):
            traits = self.data['traits'][collection]
            for row in traits.get('models', []):
                record = {**row, 'collection': collection, 'key': (collection, row['name'])}
                self.model_rows.append(record)
                for key, theme in self.themes.items():
                    accepted = (compact(collection), norm(row['name'])) in reviewed[key]
                    if accepted:
                        theme['members'].append((collection, row['name']))
            self.symbol_rows.extend({**row, 'collection': collection} for row in traits.get('symbols', []))
        self.model_lookup = {(compact(x['collection']), norm(x['name'])):x for x in self.model_rows}
        self.backdrop_lookup = {norm(x['name']):x for x in self.data.get('backdrops', [])}
        self.themes['monochrome']={'title':theme_name('monochrome'),'color':'#8296a9',
            'members':[(r['collection'],r['model']) for r in monochrome.data()['models'] if (compact(r['collection']),norm(r['model'])) in self.model_lookup]}

    def refresh(self, progress=lambda _: None):
        try:
            gifts = request('GET', 'https://api.changes.tg/gifts').json()
            backdrops = request('GET', 'https://api.changes.tg/backdrops').json()
            if not isinstance(gifts,list) or not gifts:
                raise ValueError('catalog shape')
            updated = dict(self.data.get('traits', {}))
            failures = []
            def traits(collection):
                models = request('GET', f'https://api.changes.tg/models/{quote(collection, safe="")}?sorted').json()
                symbols = request('GET', f'https://api.changes.tg/symbols/{quote(collection, safe="")}?sorted').json()
                return {'models':models, 'symbols':symbols}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                jobs = {pool.submit(traits, gift):gift for gift in gifts}
                for i,future in enumerate(concurrent.futures.as_completed(jobs),1):
                    try:
                        updated[jobs[future]] = future.result()
                    except Exception:
                        failures.append(jobs[future])
                    if i % 20 == 0:
                        progress(tr('background_catalog',count=i,total=len(gifts)))
            with self.lock:
                self.data = {'schema':2, 'collections':sorted(gifts), 'backdrops':backdrops,
                             'traits':updated, 'updated_at':time.time(), 'failures':failures}
                self.reindex()
                self.directory.mkdir(parents=True, exist_ok=True)
                tmp = self.full_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding='utf-8')
                tmp.replace(self.full_path)
            self.note = tr('catalog_updated') if not failures else tr('catalog_partial')+' ('+str(len(failures))+')'
        except Exception as error:
            self.note = tr('local_catalog')+' · ' + error_note(error)
        return self.data

    def facets(self, collection):
        traits = self.data.get('traits', {}).get(collection, {})
        return {'gift':collection, 'models':traits.get('models', []), 'symbols':traits.get('symbols', []),
                'backdrops':self.data.get('backdrops', [])}

    def selected_models(self, query):
        allowed = None
        if query.theme:
            theme = self.themes.get(query.theme)
            if theme is None:
                raise ValueError(tr('err_theme'))
            allowed = {(compact(c), norm(m)) for c,m in theme['members']}
        if query.targets:
            chosen = {(compact(c), norm(m)) for c,m in query.targets}
            allowed = chosen if allowed is None else allowed & chosen
        if query.models:
            names = {norm(x) for x in query.models}
            chosen = {(compact(r['collection']), norm(r['name'])) for r in self.model_rows if norm(r['name']) in names}
            allowed = chosen if allowed is None else allowed & chosen
        return [r for r in self.model_rows if (not query.collection or compact(r['collection']) == compact(query.collection))
                and (allowed is None or (compact(r['collection']), norm(r['name'])) in allowed)
                and (not (query.monochrome or query.mono_colors) or monochrome.has_model(r['collection'],r['name'],query.backdrops,query.mono_colors))]

    def resolve(self, query):
        from dataclasses import replace
        if query.mono_colors:
            if any(color not in monochrome.COLORS for color in query.mono_colors):raise ValueError(tr('err_color'))
            query=replace(query,monochrome=True)
        names = self.data.get('collections', [])
        if query.collection:
            canonical = next((c for c in names if compact(c) == compact(query.collection)), None)
            if not canonical:
                raise ValueError(tr('err_collection'))
            query = replace(query, collection=canonical)
        text = query.text.strip()
        if norm(text) in {norm(x) for x in ('monochrome','монохром','монохромки',theme_name('monochrome'))}:
            query=replace(query,monochrome=True,text='');text=''
        if query.theme=='monochrome':query=replace(query,theme='',monochrome=True)
        slug = re.fullmatch(r'(?:https://(?:t\.me/nft/|fragment\.com/gift/))?([A-Za-z0-9]+)-(\d+)(?:\?.*)?', text)
        if slug:
            collection = next((c for c in names if compact(c) == compact(slug[1])), None)
            if not collection or (query.collection and collection != query.collection):
                raise ValueError(tr('err_link'))
            if query.number and query.number != int(slug[2]):
                raise ValueError(tr('err_number'))
            query = replace(query, collection=collection, number=int(slug[2]), text='')
            text = ''
        if text:
            theme = next((key for key,row in THEMES.items() if norm(text) in {norm(x) for x in (*row['aliases'],theme_name(key))}), None)
            if theme:
                if query.theme and query.theme != theme:
                    raise ValueError(tr('err_theme_conflict'))
                query = replace(query, theme=theme, text='')
                text = ''
            else:
                exact = next((c for c in names if compact(c) == compact(text)), None)
                if exact:
                    if query.collection and query.collection != exact:
                        raise ValueError(tr('err_collection_conflict'))
                    query = replace(query, collection=exact, text='')
                    text = ''
        if not query.collection and not query.models and not query.targets and not query.theme and not query.monochrome and not text:
            raise ValueError(tr('err_choose'))
        filtered = bool(query.models or query.targets or query.theme or query.monochrome or text)
        if filtered:
            rows = self.selected_models(query)
            if text:
                # Full local index; no top-N remote suggestion list.
                rows = [r for r in rows if norm(text) in norm(r['name']) or norm(text) in norm(r['collection'])]
            grouped = defaultdict(list)
            for row in rows:
                grouped[row['collection']].append(row['name'])
            variants = [replace(query, collection=c, models=tuple(dict.fromkeys(models)), targets=(), theme='', text='')
                        for c,models in grouped.items()]
            if not variants:
                raise ValueError(tr('err_models'))
        else:
            variants = [replace(query, text='', theme='', targets=())]
        model_count = sum(len(x.models) for x in variants)
        if query.theme:title=theme_name(query.theme)
        elif query.collection:title=query.collection
        elif query.monochrome:title=theme_name('monochrome')
        else:title=tr('search_term',text=text)
        scope = title + (' · '+tr('scope_models',collections=len(variants),models=model_count) if filtered else '')
        return variants, scope

    def enrich(self, offer):
        row = self.model_lookup.get((compact(offer.collection), norm(offer.model)))
        if row and offer.rarity is None:
            from .core import number
            offer.rarity = number(row.get('rarity'))
        backdrop = self.backdrop_lookup.get(norm(offer.backdrop))
        if backdrop:
            palette = backdrop.get('hex', {})
            offer.colors = {'center':palette.get('centerColor', '#35465a'), 'edge':palette.get('edgeColor', '#1b2636'),
                            'pattern':palette.get('patternColor', '#0c1520')}
        return offer
