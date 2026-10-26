from dataclasses import replace
from decimal import Decimal
import threading

import pytest
import requests

from giftfinder import catalogue, providers
from giftfinder.core import Offer, SearchQuery, SearchResult, SourceStatus, merge_offers


class OneQueryCatalog:
    def __init__(self, directory): self.directory = directory
    def resolve(self, query): return [query], 'audit regression'


def indexed_offer(market='telegram', amount='100', checked_at=1000):
    return Offer('EasterEgg-42', 'Easter Egg', 42, market, Decimal(amount), 'TON',
                 'Creeper', 'Black', 'Bread', source='browse.tg', checked_at=checked_at)


@pytest.mark.parametrize('market', ['telegram','getgems','mrkt','tonnel'])
def test_fresh_index_replaces_cached_price_in_current_search_and_progress(tmp_path, monkeypatch, market):
    engine = providers.SearchEngine(OneQueryCatalog(tmp_path))
    old = indexed_offer(market); fresh = replace(old, amount=Decimal('10'), checked_at=2000)
    engine.cache.save([old]); calls = []; snapshots = []
    def index(query, **kwargs):
        calls.append(query)
        return SearchResult([fresh], [SourceStatus(market, 'ok', source='browse.tg', checked_at=2000)])
    monkeypatch.setattr(providers, 'index_search', index)
    query = SearchQuery(collection='Easter Egg', markets=(market,))
    result = engine.search(query, on_update=lambda batch: snapshots.append([(offer.amount,offer.source) for offer in batch.offers]))
    assert calls == [query]
    assert snapshots[0] == [(Decimal('100'),'local-cache')]
    assert snapshots[-1] == [(Decimal('10'),'browse.tg')]
    assert result.offers[0].amount == Decimal('10') and not result.offers[0].stale
    assert engine.cache.find([query]).offers[0].amount == Decimal('10')


def test_older_index_does_not_overwrite_a_newer_saved_price(tmp_path, monkeypatch):
    engine = providers.SearchEngine(OneQueryCatalog(tmp_path))
    old = indexed_offer(checked_at=2000); stale_index = replace(old, amount=Decimal('10'), checked_at=1000)
    engine.cache.save([old])
    monkeypatch.setattr(providers, 'index_search', lambda *args, **kwargs: SearchResult([stale_index]))
    result = engine.search(SearchQuery(collection='Easter Egg', markets=('telegram',)))
    assert result.offers[0].amount == Decimal('100')
    assert result.offers[0].source == 'local-cache' and result.offers[0].stale


@pytest.mark.parametrize('direct_first', [False, True])
def test_live_direct_response_keeps_priority_over_index_even_if_price_increases(direct_first):
    index = indexed_offer('fragment', '10', 2000)
    direct = replace(index, source='direct', amount=Decimal('100'), checked_at=1000)
    left, right = (direct,index) if direct_first else (index,direct)
    assert merge_offers([left], [right])[0] is direct


def test_missing_portals_mapping_is_not_a_complete_empty_listing_response(monkeypatch):
    monkeypatch.setattr(providers, '_portals_collections', {'collections':[]})
    monkeypatch.setattr(providers, 'request', lambda *args, **kwargs: pytest.fail('Do not add a metadata refresh or listing request'))
    result = providers.portals_search(SearchQuery(collection='Easter Egg', markets=('portals',)))
    assert not result.offers and len(result.statuses) == 1
    assert result.statuses[0].state == 'unavailable' and not result.statuses[0].complete


@pytest.mark.parametrize('index_available', [False, True])
def test_missing_portals_metadata_never_purges_index_or_saved_offers(tmp_path, monkeypatch, index_available):
    engine = providers.SearchEngine(OneQueryCatalog(tmp_path))
    old = indexed_offer('portals'); fresh = replace(old, amount=Decimal('10'), checked_at=2000)
    engine.cache.save([old]); calls = []
    monkeypatch.setattr(providers, '_portals_collections', {'collections':[]})
    monkeypatch.setattr(providers, 'request', lambda *args, **kwargs: pytest.fail('Do not add a metadata refresh or listing request'))
    def index(query, **kwargs):
        calls.append(query)
        if not index_available: raise requests.Timeout()
        return SearchResult([fresh], [SourceStatus('portals','ok',source='browse.tg',checked_at=2000)])
    monkeypatch.setattr(providers, 'index_search', index)
    query = SearchQuery(collection='Easter Egg', markets=('portals',))
    result = engine.search(query)
    assert calls == [query]
    assert len(result.offers) == 1
    assert result.offers[0].amount == Decimal('10' if index_available else '100')
    assert len(engine.cache.find([query]).offers) == 1
    assert not any(status.complete for status in result.statuses if status.source == 'direct')
    assert result.progress['errors'] >= 1


def test_reindex_keeps_complete_public_indexes_and_serializes_actual_search_readers(tmp_path, monkeypatch):
    catalog = catalogue.Catalog(tmp_path)
    query = SearchQuery(collection='Input Key', models=('Creeper',))
    expected = catalog.resolve(query)
    original_models = catalog.model_rows; original_themes = catalog.themes
    entered = threading.Event(); release = threading.Event(); reader_started = threading.Event()
    writer_id = []; failures = []; results = []
    norm = catalogue.norm
    def paused(value):
        if writer_id and threading.get_ident() == writer_id[0] and not entered.is_set():
            entered.set()
            if not release.wait(5): raise AssertionError('Reader test did not release the catalog writer')
        return norm(value)
    monkeypatch.setattr(catalogue, 'norm', paused)
    def writer():
        writer_id.append(threading.get_ident())
        try: catalog.reindex()
        except BaseException as error: failures.append(error)
    def reader():
        reader_started.set()
        try: results.append(catalog.resolve(query))
        except BaseException as error: failures.append(error)
    write_thread = threading.Thread(target=writer); read_thread = threading.Thread(target=reader)
    write_thread.start()
    try:
        assert entered.wait(5)
        assert catalog.model_rows is original_models and catalog.themes is original_themes
        assert catalog.model_rows and catalog.themes['minecraft']['members']
        read_thread.start(); assert reader_started.wait(5)
    finally:
        release.set(); write_thread.join(5)
        if read_thread.ident is not None: read_thread.join(5)
    assert not write_thread.is_alive() and not read_thread.is_alive()
    assert not failures and results == [expected]


@pytest.mark.parametrize('key,alias', [
    ('pepe','PP'), ('pepe','ПП'), ('gold','золото'), ('silver','Silver'),
    ('star_wars','звёздные войны'), ('harry_potter','Гарри Поттер'), ('pokemon','Pokémon'),
    ('sailor_moon','сейлор мун'), ('doge','Doge'), ('space','космос'),
])
def test_new_theme_aliases_resolve_only_the_explicit_curated_members(tmp_path, monkeypatch, key, alias):
    catalog = catalogue.Catalog(tmp_path)
    selected = next(row for row in catalog.model_rows if row['collection'] == 'Plush Pepe')
    pair = (selected['collection'], selected['name'])
    # A one-member reviewed fixture proves aliases select a group instead of
    # expanding its membership from words in other model names.
    theme = {'key':key, 'color':'#819cab', 'members':[pair], 'aliases':catalogue._aliases[key]}
    monkeypatch.setattr(catalogue, 'THEMES', {**catalogue.THEMES, key:theme})
    catalog.reindex()
    variants, _ = catalog.resolve(SearchQuery(text=alias))
    assert {(query.collection,model) for query in variants for model in query.models} == {pair}
