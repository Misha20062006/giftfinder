"""Audited model/backdrop pairs; runtime lookup only, no image processing or network."""
import json,re
from functools import lru_cache
from pathlib import Path

COLORS={'black':'#24272c','gray':'#9299a3','white':'#eeece5','brown':'#80533b',
        'red':'#e9454c','orange':'#f09235','yellow':'#f2d74c','green':'#55b851',
        'teal':'#42c3b9','blue':'#4897e8','violet':'#8d75df','purple':'#c15bd5','pink':'#ed84b4'}

def canonical(value):return re.sub(r'\s+',' ',str(value)).strip().casefold()
def collection_key(value):return re.sub('[^a-z0-9]','',canonical(value))

@lru_cache(maxsize=1)
def data():
    path=Path(__file__).parent/'monochrome_pairs.json'
    return json.loads(path.read_text(encoding='utf-8'))

@lru_cache(maxsize=1)
def index():
    return {(collection_key(r['collection']),canonical(r['model'])):tuple(r['backdrops']) for r in data()['models']}

def backgrounds(collection,model):return index().get((collection_key(collection),canonical(model)),())

@lru_cache(maxsize=1)
def families():
    return {(collection_key(r['collection']),canonical(r['model'])):r['family'] for r in data()['models']}

def family(collection,model):return families().get((collection_key(collection),canonical(model)),'')

@lru_cache(maxsize=16384)
def allowed(collection,model,backdrop,colors=()):
    return (not colors or family(collection,model) in colors) and canonical(backdrop) in {canonical(b) for b in backgrounds(collection,model)}

def has_model(collection,model,backdrops=(),colors=()):
    values=backgrounds(collection,model)
    return bool(values) and (not colors or family(collection,model) in colors) and (not backdrops or bool({canonical(b) for b in values}&{canonical(b) for b in backdrops}))
