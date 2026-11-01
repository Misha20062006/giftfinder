"""New gifts, live data updates and offline fallbacks use the same search path."""
import copy
import hashlib
import json
import threading
import time
from decimal import Decimal

import pytest
import requests

from giftfinder import catalogue, monochrome, providers, reference_data
from giftfinder.catalogue import Catalog
from giftfinder.core import Offer, SearchQuery, SearchResult
from giftfinder.reference_data import FILES, ReferenceStore


class Response:
    def __init__(self, value):
        self.content = (value if isinstance(value,str) else json.dumps(value)).encode('utf-8')
    def json(self): return json.loads(self.content)


def bundle():
    root = reference_data.Path(reference_data.__file__).parent
    values = {name:json.loads((root/name).read_text(encoding='utf-8')) for name in FILES}
    data = values['catalog_full.json']
    data['collections'].append('Future Gift')
    data['traits']['Future Gift'] = {'models':[{'name':'Future Black'}], 'symbols':[]}
    values['themes_curated.json']['themes'][0]['members'].append(['Future Gift','Future Black'])
    values['monochrome_pairs.json']['models'].append({'collection':'Future Gift','model':'Future Black','family':'black','backdrops':['Black']})
    content = {name:json.dumps(value) for name,value in values.items()}
    manifest = {'schema':1, 'updated_at':int(time.time())+1, 'files':{name:hashlib.sha256(raw.encode('utf-8')).hexdigest() for name,raw in content.items()}}
    return {'manifest':manifest,'files':content}


def serve(monkeypatch, value):
    calls = []
    def get(method, url):
        calls.append(url)
        name = url.rsplit('/',1)[-1]
        return Response(value['manifest'] if name == 'catalog_updates.json' else value['files'][name])
    monkeypatch.setattr(reference_data,'request',get)
    return calls


def unavailable(*args, **kwargs): raise requests.ConnectionError('offline')


def test_new_collection_and_models_are_searchable_and_persist_without_restart(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path)
    def get(method,url):
        if url.endswith('/gifts'): return Response(['Future Gift'])
        if url.endswith('/backdrops'): return Response(catalog.data['backdrops'])
        return Response([{'name':'Future Model'}] if '/models/' in url else [])
    monkeypatch.setattr(catalogue,'request',get)
    catalog.refresh(include_references=False)
    assert catalog.resolve(SearchQuery(collection='Future Gift',models=('Future Model',)))[0][0].models == ('Future Model',)
    assert 'Easter Egg' in catalog.data['collections']
    assert Catalog(tmp_path).resolve(SearchQuery(text='Future Model'))[0][0].collection == 'Future Gift'


def test_bad_trait_response_keeps_previous_models_and_marks_partial(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path)
    before = catalog.facets('Easter Egg')['models']
    def get(method,url):
        if url.endswith('/gifts'): return Response(['Easter Egg'])
        if url.endswith('/backdrops'): return Response(catalog.data['backdrops'])
        return Response({'unexpected':'shape'})
    monkeypatch.setattr(catalogue,'request',get)
    catalog.refresh(include_references=False)
    assert catalog.facets('Easter Egg')['models'] == before
    assert catalog.data['failures'] == ['Easter Egg']


def test_reviewed_theme_and_monochrome_updates_reach_workers_cache_and_offline_restart(tmp_path, monkeypatch):
    value = bundle(); calls = serve(monkeypatch,value)
    monkeypatch.setattr(catalogue,'request',unavailable)
    catalog = Catalog(tmp_path); catalog.refresh()
    assert len(calls) == 4
    assert ('Future Gift','Future Black') in catalog.themes['minecraft']['members']
    assert catalog.monochrome.has_model('Future Gift','Future Black',colors=('black',))
    offer = Offer('FutureGift-1','Future Gift',1,'telegram',Decimal('10'),'TON','Future Black','Black')
    def index(query, **kwargs):
        assert query.matches(offer)
        assert not query.matches(copy.copy(Offer('FutureGift-2','Future Gift',2,'telegram',Decimal('10'),'TON','Future Black','White')))
        return SearchResult([offer])
    monkeypatch.setattr(providers,'index_search',index)
    engine = providers.SearchEngine(catalog)
    query = SearchQuery(collection='Future Gift',theme='minecraft',mono_colors=('black',),markets=('telegram',))
    assert engine.search(query).offers[0].slug == offer.slug
    assert engine.cached(query).offers[0].slug == offer.slug
    assert not monochrome.has_model('Future Gift','Future Black')  # isolated from other profiles
    restored = Catalog(tmp_path)
    assert restored.resolve(query)[0]
    assert providers.SearchEngine(restored).cached(query).offers[0].slug == offer.slug


def test_unchanged_manifest_does_not_redownload_data(tmp_path, monkeypatch):
    calls = serve(monkeypatch,bundle()); store = ReferenceStore(tmp_path)
    store.refresh(); store.refresh()
    assert len(calls) == 5


def test_older_reference_update_cannot_replace_newer_data(tmp_path, monkeypatch):
    value = bundle(); serve(monkeypatch,value)
    store = ReferenceStore(tmp_path); store.refresh(); before = store.path.read_bytes()
    old = copy.deepcopy(value); old['manifest']['updated_at'] -= 1
    calls = serve(monkeypatch,old)
    with pytest.raises(ValueError,match='Outdated'): store.refresh()
    assert len(calls) == 1 and store.path.read_bytes() == before


@pytest.mark.parametrize('corrupt',[{'manifest':[],'files':{}}, {'manifest':{},'files':None}, []])
def test_corrupt_reference_cache_does_not_break_startup(tmp_path, corrupt):
    (tmp_path/'reference-data.json').write_text(json.dumps(corrupt),encoding='utf-8')
    catalog = Catalog(tmp_path)
    assert catalog.resolve(SearchQuery(collection='Easter Egg'))[0]


@pytest.mark.parametrize('failure',['checksum','missing_theme','malformed_json'])
def test_broken_update_keeps_last_valid_cache_and_searches(tmp_path, monkeypatch, failure):
    valid = bundle(); serve(monkeypatch,valid)
    store = ReferenceStore(tmp_path); store.refresh(); before = store.path.read_bytes()
    invalid = copy.deepcopy(valid)
    if failure == 'checksum': invalid['files']['themes_curated.json'] += ' '
    else:
        name = 'themes_curated.json'
        invalid['files'][name] = '{' if failure == 'malformed_json' else json.dumps({'themes':[]})
        invalid['manifest']['files'][name] = hashlib.sha256(invalid['files'][name].encode('utf-8')).hexdigest()
    # Change the manifest so a mismatched file is actually checked.
    if failure == 'checksum': invalid['manifest']['revision'] = 'broken'
    serve(monkeypatch,invalid)
    with pytest.raises(ValueError): store.refresh()
    assert store.path.read_bytes() == before
    assert ReferenceStore(tmp_path).payloads == store.payloads


def test_older_profile_catalog_does_not_hide_new_bundled_metadata(tmp_path):
    (tmp_path/'catalog-v2.json').write_text(json.dumps({'collections':['Old Gift'],'backdrops':[],
        'traits':{'Old Gift':{'models':[{'name':'Old Model'}],'symbols':[]}}}),encoding='utf-8')
    catalog = Catalog(tmp_path)
    assert 'Old Gift' in catalog.data['collections'] and 'Easter Egg' in catalog.data['collections']
    assert catalog.resolve(SearchQuery(collection='Old Gift'))[0]


def test_parallel_catalog_refresh_does_not_duplicate_requests(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path)
    assert catalog.refresh_lock.acquire(blocking=False)
    monkeypatch.setattr(catalogue,'request',lambda *a,**k: pytest.fail('Overlapping refresh'))
    try: assert catalog.refresh(include_references=False) is catalog.data
    finally: catalog.refresh_lock.release()


def test_portals_refreshes_expired_metadata_and_follows_every_page(monkeypatch):
    monkeypatch.setattr(providers,'_portals_collections',{'collections':[]})
    monkeypatch.setattr(providers,'_portals_updated_at',time.monotonic()-1000)
    calls=[]
    def get(method,url,params):
        calls.append(params['offset'])
        start=params['offset']; count=200 if start == 0 else 1
        return Response({'collections':[{'id':str(i),'name':'Future Gift' if i == 200 else f'Gift {i}'} for i in range(start,start+count)]})
    monkeypatch.setattr(providers,'request',get)
    assert providers.portals_catalog()['collections'][-1]['name'] == 'Future Gift'
    assert len(providers.portals_catalog()['collections']) == 201 and calls == [0,200]


def test_portals_incomplete_metadata_does_not_replace_cache(monkeypatch):
    original={'collections':[{'id':'old','name':'Old Gift'}]}
    monkeypatch.setattr(providers,'_portals_collections',original)
    monkeypatch.setattr(providers,'_portals_updated_at',0)
    monkeypatch.setattr(providers,'request',lambda *a,**k:Response({'unexpected':[]}))
    with pytest.raises(ValueError): providers.portals_catalog()
    assert providers._portals_collections is original


def test_portals_repeated_collection_page_is_not_published(monkeypatch):
    monkeypatch.setattr(providers,'_portals_collections',None)
    monkeypatch.setattr(providers,'request',lambda *a,**k:Response({'collections':[{'id':str(i),'name':f'Gift {i}'} for i in range(200)]}))
    with pytest.raises(ValueError): providers.portals_catalog()
    assert providers._portals_collections is None


def test_running_search_keeps_its_monochrome_snapshot_on_refresh(tmp_path, monkeypatch):
    catalog = Catalog(tmp_path)
    lookup = monochrome.Lookup(ReferenceStore.decode(bundle())['monochrome_pairs.json'])
    catalog.monochrome = lookup
    catalog._apply_references(ReferenceStore.decode(bundle())); catalog.reindex()
    offer = Offer('FutureGift-1','Future Gift',1,'telegram',Decimal('10'),'TON','Future Black','Black')
    def index(query,**kwargs):
        catalog.monochrome = monochrome.Lookup()
        assert query.matches(offer)
        return SearchResult([offer])
    monkeypatch.setattr(providers,'index_search',index)
    result = providers.SearchEngine(catalog).search(SearchQuery(collection='Future Gift',mono_colors=('black',),markets=('telegram',)))
    assert result.offers == [offer]


@pytest.mark.parametrize('mobile',[False,True])
def test_background_catalog_update_preserves_filter_draft_and_profile(tmp_path, monkeypatch, mobile):
    from PySide6.QtWidgets import QApplication
    from giftfinder.ui import MainWindow
    from giftfinder.ui_common import application
    from giftfinder.mobile_ui import MobileWindow
    app = QApplication.instance() or application()
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR',str(tmp_path))
    window = (MobileWindow if mobile else MainWindow)(offline=True)
    try:
        query = SearchQuery(collection='Easter Egg',models=('Creeper',))
        window.filter_query=query; window.search_edit.setText('draft')
        window.open_filters('models',query)
        draft = window.filter_dialog.state
        window.catalog._apply_references(ReferenceStore.decode(bundle())); window.catalog.reindex()
        window.catalog_ready(None)
        assert window.search_edit.text() == 'draft' and window.filter_query == query
        assert window.filter_dialog.state == draft
        assert 'Future Gift' in {r['name'] for r in window.home_model.rows}
    finally:
        window.close(); app.processEvents(); window.pool.waitForDone()
