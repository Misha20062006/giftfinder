"""Audited model/backdrop pairs; runtime lookup only, no image processing or network."""
import json,re
from functools import lru_cache
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar

COLORS={'black':'#24272c','gray':'#9299a3','white':'#eeece5','brown':'#80533b',
        'red':'#e9454c','orange':'#f09235','yellow':'#f2d74c','green':'#55b851',
        'teal':'#42c3b9','blue':'#4897e8','violet':'#8d75df','purple':'#c15bd5','pink':'#ed84b4'}

def canonical(value):return re.sub(r'\s+',' ',str(value)).strip().casefold()
def collection_key(value):return re.sub('[^a-z0-9]','',canonical(value))

@lru_cache(maxsize=1)
def _bundled_data():
    path=Path(__file__).parent/'monochrome_pairs.json'
    return json.loads(path.read_text(encoding='utf-8'))

class Lookup:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else _bundled_data()
        self.rows = {(collection_key(r['collection']),canonical(r['model'])):(r['family'],tuple(r['backdrops']),frozenset(map(canonical,r['backdrops']))) for r in self.payload['models']}

    def backgrounds(self, collection, model):
        return self.rows.get((collection_key(collection),canonical(model)), ('',(),frozenset()))[1]

    def family(self, collection, model):
        return self.rows.get((collection_key(collection),canonical(model)), ('',(),frozenset()))[0]

    def allowed(self, collection, model, backdrop, colors=()):
        family, _, backgrounds = self.rows.get((collection_key(collection),canonical(model)), ('',(),frozenset()))
        return (not colors or family in colors) and canonical(backdrop) in backgrounds

    def has_model(self, collection, model, backdrops=(), colors=()):
        family, values, backgrounds = self.rows.get((collection_key(collection),canonical(model)), ('',(),frozenset()))
        return bool(values) and (not colors or family in colors) and (not backdrops or bool(set(map(canonical,backdrops)) & backgrounds))


_active = ContextVar('giftfinder_monochrome', default=None)


@lru_cache(maxsize=1)
def _default(): return Lookup()


@contextmanager
def use(lookup):
    token = _active.set(lookup)
    try: yield
    finally: _active.reset(token)


def current(): return _active.get() or _default()


def data(): return current().payload


def index():
    return {key:row[1] for key,row in current().rows.items()}

def backgrounds(collection,model):return current().backgrounds(collection,model)

def families():
    return {key:row[0] for key,row in current().rows.items()}

def family(collection,model):return current().family(collection,model)

def allowed(collection,model,backdrop,colors=()):
    return current().allowed(collection,model,backdrop,colors)

def has_model(collection,model,backdrops=(),colors=()):
    return current().has_model(collection,model,backdrops,colors)
