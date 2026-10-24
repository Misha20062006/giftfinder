import json
import threading
from dataclasses import replace
from decimal import Decimal

from giftfinder import providers as p
from giftfinder.catalogue import Catalog, query_from_dict
from giftfinder.currency import RateBook, parse_stars_price
from giftfinder.cache import ListingCache
from giftfinder.core import Offer, SearchQuery, SearchResult, SourceStatus, Store


def item(n=42, **kwargs):
    fields = dict(slug=f'EasterEgg-{n}',collection='Easter Egg',number=n,market='fragment',amount=Decimal('10'),currency='TON',
                  model='Creeper',backdrop='Black',symbol='Bread',source='direct',checked_at=100)
    return Offer(**{**fields,**kwargs})


def test_full_catalog_search_and_exact_pair_membership(tmp_path,monkeypatch):
    monkeypatch.setattr(p,'request',lambda *a,**k: (_ for _ in ()).throw(AssertionError('Local search used network')))
    c = Catalog(tmp_path)
    assert len(c.data['collections']) >= 123 and len(c.model_rows) >= 7806
    assert len(c.backdrop_lookup) == 80
    q,_ = c.resolve(SearchQuery(text='cake'))
    # More than a short autocomplete page, and all model matches are retained.
    expected = {(r['collection'],r['name']) for r in c.model_rows if 'cake' in r['name'].casefold() or 'cake' in r['collection'].casefold()}
    actual = {(v.collection,m) for v in q for m in v.models}
    assert actual == expected and len(actual) > 10
    pairs = (('Easter Egg','Creeper'),('Scared Cat','Endercat'))
    variants,_ = c.resolve(SearchQuery(targets=pairs))
    assert {(v.collection,m) for v in variants for m in v.models} == set(pairs)
    assert not SearchQuery(targets=pairs).matches(item(collection='Scared Cat',model='Creeper'))


def test_curated_themes_do_not_expand_from_keywords(tmp_path):
    c = Catalog(tmp_path)
    mc = set(c.themes['minecraft']['members'])
    assert ('Easter Egg','Creeper') in mc
    assert ('Snow Globe','Minehouse') in mc
    assert ('Restless Jar','Miniland') not in mc
    assert ('Lunar Snake','Redstone') not in mc
    assert ('Lunar Snake','Lapis') not in mc
    assert ('Lunar Snake','Fromage') in c.themes['cheese']['members']
    c.data['traits']['Easter Egg']['models'].append({'name':'Minecraft Mystery'})
    c.reindex()
    assert ('Easter Egg','Minecraft Mystery') not in c.themes['minecraft']['members']


def test_profile_and_legacy_saved_search_migration(tmp_path):
    store = Store(tmp_path); store.toggle(item())
    store.data['settings']['rub_per_star'] = '2'
    store.data['searches'] = [{'collection':'Easter Egg','models':['Creeper'],'backdrops':['Black'],'price_min':'1','price_currency':'TON'}]
    store.save()
    (tmp_path/'catalog.json').write_text(json.dumps({'collections':['Easter Egg'],'backdrops':[]}),encoding='utf-8')
    c = Catalog(tmp_path)
    assert len(c.data['collections'])>=123
    q = query_from_dict(Store(tmp_path).data['searches'][0])
    assert q.models == ('Creeper',) and c.resolve(q)[0]
    assert Store(tmp_path).data['settings']['rub_per_star'] == '2'
    assert Store(tmp_path).favorites()[0].amount == Decimal('10')
    assert Store(tmp_path).favorites()[0].price_label == '10 GRAM'


def test_cache_keeps_native_price_timestamp_and_scope(tmp_path):
    cache = ListingCache(tmp_path)
    direct = item(); other = item(43,model='Chicken')
    cache.save([direct,other])
    cache.save([replace(direct,source='browse.tg',checked_at=1000,amount=Decimal('999'))])
    rows = cache.find([SearchQuery(collection='Easter Egg',models=('Creeper',))]).offers
    assert len(rows) == 1 and rows[0].amount == Decimal('10') and rows[0].checked_at == 100
    assert rows[0].stale and rows[0].source == 'local-cache'
    cache.remove_absent(SearchQuery(collection='Easter Egg',models=('Creeper',)),'fragment',set())
    assert [o.slug for o in cache.find([SearchQuery(collection='Easter Egg')]).offers] == ['EasterEgg-43']


def test_progressive_pages_and_late_index_do_not_restore_absent_offer(monkeypatch):
    released = threading.Event(); snapshots = []; pages = []
    class C:
        def resolve(self,q): return [q],'scope'
    q = SearchQuery(collection='Easter Egg',markets=('fragment',))
    def native(query,known,offset='',**kwargs):
        pages.append(offset)
        if not offset:
            return SearchResult([item(1)],[SourceStatus('fragment','ok',source='direct')],
                                [{'provider':'fragment','offset':'second','query':{}}])
        released.set()
        return SearchResult([item(2)],[SourceStatus('fragment','ok',source='direct')])
    def index(query,**kwargs):
        assert released.wait(3)
        return SearchResult([item(3,source='browse.tg')])
    monkeypatch.setattr(p,'fragment_search',native); monkeypatch.setattr(p,'index_search',index)
    result = p.SearchEngine(C()).search(q,on_update=lambda result:snapshots.append(result))
    assert pages == ['', 'second']
    assert {o.number for o in result.offers} == {1,2}
    assert any(len(s.offers) == 1 for s in snapshots)
    assert next(s for s in result.statuses if s.source == 'direct').complete


def test_partial_earlier_page_never_invalidates_cache(tmp_path,monkeypatch):
    c = Catalog(tmp_path); engine = p.SearchEngine(c); engine.cache.save([item(99)])
    def native(query,known,offset='',**kwargs):
        if not offset:
            return SearchResult([item(1)],[SourceStatus('fragment','partial',source='direct')],
                                [{'provider':'fragment','offset':'second','query':{}}])
        return SearchResult([item(2)],[SourceStatus('fragment','ok',source='direct')])
    monkeypatch.setattr(p,'fragment_search',native); monkeypatch.setattr(p,'index_search',lambda *a,**k:SearchResult())
    result = engine.search(SearchQuery(collection='Easter Egg',models=('Creeper',),markets=('fragment',)))
    assert {o.number for o in result.offers} == {1,2,99}
    assert not next(s for s in result.statuses if s.source == 'direct').complete


def test_currency_cross_conversion_retains_original_and_precise_sort_values(tmp_path):
    rates = RateBook(tmp_path)
    rates.data = {'fx':{'USD':'1','RUB':'80','EUR':'0.9'},'gram_usd':'2','star_usd':'0.015'}
    gram = item(amount=Decimal('1.25')); star = item(43,amount=Decimal('1000'),currency='Stars')
    assert rates.convert(gram,'RUB') == Decimal('200')
    assert rates.convert(star,'RUB') == Decimal('1200')
    assert rates.convert(star,'USD') == Decimal('15')
    assert rates.convert(star,'GRAM') == Decimal('7.5')
    assert rates.convert(star,'Stars') == Decimal('1000')
    assert rates.convert(star,'EUR') == Decimal('13.5')
    assert rates.convert(star,'NOTREAL') is None
    assert star.amount == Decimal('1000') and star.currency == 'Stars'


def test_stars_price_uses_public_purchase_package():
    html = '<div class="js-stars-options">'+''.join(
        f'<label class="tm-form-radio-item"><input name="stars" value="{q}"><span class="icon-usd">{price}</span></label>'
        for q,price in ((50,'0.76'),(1000,'15.00'),(10000,'150.00')))+ '</div> '
    result = parse_stars_price(html)
    assert result['star_usd'] == '0.015'
    assert '1000' in result['star_source']


def test_rate_refresh_partial_outage_preserves_dated_rates(tmp_path,monkeypatch):
    from giftfinder import currency
    rates = RateBook(tmp_path); old = dict(rates.data)
    monkeypatch.setattr(currency,'request',lambda *a,**kw: (_ for _ in ()).throw(ConnectionError()))
    rates.refresh()
    assert rates.data['fx'] == old['fx'] and rates.data['gram_updated'] == old['gram_updated']
    assert rates.error and 'UTC' in rates.note()
