from dataclasses import replace
from decimal import Decimal

import pytest
import requests

from giftfinder.core import Offer, SearchQuery, SearchResult, SourceStatus
from giftfinder import providers as p


def payload():
    return {
        'gift': 'Easter Egg', 'markets': {'telegram': {'state': 'stale', 'fetchedAt': 1700000000, 'complete': False, 'capped': True}},
        'rows': [dict(slug='EasterEgg-42', number=42, market='telegram', model='Creeper', backdrop='Black', symbol='Bread',
                      priceTon=10, stars=900, seenAt=1700000000, link='https://t.me/nft/EasterEgg-42', stale=True)]
    }


def test_index_keeps_stars_and_real_source_timestamp():
    result = p.parse_index(payload(), SearchQuery(collection='Easter Egg', backdrops=('Black',)))
    item = result.offers[0]
    assert item.currency == 'Stars' and item.amount == Decimal('900')
    assert item.checked_at == 1700000000 and item.stale
    assert not next(s for s in result.statuses if s.market == 'telegram').complete
    assert not p.parse_index(payload(), SearchQuery(backdrops=('Onyx Black',))).offers


def test_unknown_and_zero_prices_are_not_free_offers():
    data = payload()
    data['rows'][0]['stars'] = None
    data['rows'][0]['priceTon'] = None
    assert not p.parse_index(data, SearchQuery()).offers
    data['rows'][0]['priceTon'] = 0
    assert not p.parse_index(data, SearchQuery()).offers


def test_fragment_detail_requires_buy_button_and_reads_exact_attributes():
    html = '''<table><tr><td class="table-cell">Model</td><td class="table-cell"><a class="table-cell-value-link">Creeper</a>2%</td></tr>
    <tr><td class="table-cell">Backdrop</td><td class="table-cell"><a class="table-cell-value-link">Black</a>1%</td></tr></table>
    <button>Buy for 80</button>'''
    result = p.fragment_detail(html)
    assert result['model'] == 'Creeper' and result['backdrop'] == 'Black'
    assert result['buyable'] and result['amount'] == Decimal('80')
    assert result['rarity'] == Decimal('2')
    assert not p.fragment_detail(html.replace('<button>Buy for 80</button>', '<p>Sold for 80</p>'))['buyable']


def test_public_read_request_is_not_retried_on_429(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(args)
        response = requests.Response()
        response.status_code = 429
        return response
    monkeypatch.setattr(p.requests, 'request', request)
    with pytest.raises(requests.HTTPError):
        p.request('GET', 'https://fragment.com/gifts')
    assert len(calls) == 1


def test_fresh_complete_source_removes_old_cached_listings_only_within_scope(monkeypatch):
    def item(n, market='fragment'):
        return Offer(f'EasterEgg-{n}', 'Easter Egg', n, market, Decimal('199'), 'TON', model='Creeper', backdrop='Black')
    cached = SearchResult(offers=[item(1), item(2, 'telegram')])
    fresh = SearchResult(offers=[replace(item(3), source='direct', amount=Decimal('80'))],
                         statuses=[SourceStatus('fragment', 'ok', complete=True, source='direct')])
    monkeypatch.setattr(p, 'index_search', lambda q, **_: cached)
    monkeypatch.setattr(p, 'fragment_search', lambda q, known, **_: fresh)
    class Catalog:
        def resolve(self, q):
            return [q], 'scope'
    result = p.SearchEngine(Catalog()).search(SearchQuery(collection='Easter Egg', markets=('fragment', 'telegram')))
    assert {o.slug for o in result.offers} == {'EasterEgg-2', 'EasterEgg-3'}


def test_failed_direct_source_preserves_labeled_cache(monkeypatch):
    data = p.parse_index(payload(), SearchQuery(markets=('telegram', 'fragment')))
    monkeypatch.setattr(p, 'index_search', lambda q, **_: data)
    def failure(*args, **kwargs):
        raise requests.Timeout()
    monkeypatch.setattr(p, 'fragment_search', failure)
    class Catalog:
        def resolve(self, q):
            return [q], 'scope'
    result = p.SearchEngine(Catalog()).search(SearchQuery(collection='Easter Egg', markets=('fragment', 'telegram')))
    assert len(result.offers) == 1 and result.offers[0].stale
    assert any(s.market == 'fragment' and s.state == 'unavailable' for s in result.statuses)


def test_catalog_resolution_never_ignores_conflicting_filters(tmp_path):
    catalog = p.Catalog(tmp_path, tmp_path / 'none.json')
    catalog.data['collections'] = ['Easter Egg', 'Plush Pepe']
    from giftfinder.i18n import tr
    with pytest.raises(ValueError) as conflict:
        catalog.resolve(SearchQuery(collection='Easter Egg', text='Plush Pepe'))
    assert str(conflict.value) == tr('err_collection_conflict')
    with pytest.raises(ValueError) as wrong_link:
        catalog.resolve(SearchQuery(collection='Plush Pepe', text='https://t.me/nft/EasterEgg-42'))
    assert str(wrong_link.value) == tr('err_link')
    variants, _ = catalog.resolve(SearchQuery(text='https://t.me/nft/EasterEgg-42'))
    assert variants[0].collection == 'Easter Egg' and variants[0].number == 42


def test_cancelled_search_does_not_start_new_network_requests(monkeypatch):
    import threading
    cancelled = threading.Event()
    cancelled.set()
    def forbidden(*args, **kwargs):
        raise AssertionError('A request started after cancellation')
    monkeypatch.setattr(p, 'request', forbidden)
    q = SearchQuery(collection='Easter Egg')
    assert not p.index_search(q, cancelled).offers
    assert not p.portals_search(q, cancelled=cancelled).offers
    assert not p.fragment_search(q, {}, cancelled=cancelled).offers
