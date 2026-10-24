from __future__ import annotations

import concurrent.futures
import itertools
import json
import re
import threading
import time
from dataclasses import asdict, replace
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup

from .i18n import tr, theme_name
from .core import (MARKETS, Offer, SearchQuery, SearchResult, SourceStatus,
                   compact, merge_offers, norm, number, safe_url, stamp)

USER_AGENT = 'GiftFinder/0.6 (Windows; read-only gift search)'
TIMEOUT = (8, 22)


def request(method: str, url: str, session=None, **kwargs):
    caller = session or requests
    response = caller.request(method, url, timeout=TIMEOUT,
                              headers={'User-Agent': USER_AGENT, 'Accept': 'application/json,text/html'}, **kwargs)
    response.raise_for_status()
    return response


def error_note(error) -> str:
    if isinstance(error, requests.HTTPError):
        code = error.response.status_code
        return {401: tr('err_auth'), 403: tr('err_denied'),
                429: tr('err_limit')}.get(code, tr('err_http',code=code))
    if isinstance(error, requests.Timeout):
        return tr('err_timeout')
    if isinstance(error, requests.ConnectionError):
        return tr('err_connection')
    return tr('err_response')


def parse_index(payload: dict, query: SearchQuery) -> SearchResult:
    result = SearchResult()
    states = payload.get('markets', {})
    for market in query.markets:
        state = states.get(market, {})
        raw_state = state.get('state', 'unavailable')
        status = SourceStatus(market, raw_state, int(state.get('count') or 0), stamp(state.get('fetchedAt')),
                              bool(state.get('complete')) and not bool(state.get('capped')), 'browse.tg',
                              tr('index_note'))
        if state.get('capped'):
            status.note += ' '+tr('partial_source')
        if state.get('loading') or payload.get('updating'):
            status.note += ' '+tr('index_updating')
        result.statuses.append(status)
    for row in payload.get('rows', []):
        market = row.get('market')
        if market not in query.markets:
            continue
        currency = 'Stars' if row.get('stars') is not None else 'TON'
        amount = number(row.get('stars') if currency == 'Stars' else row.get('priceTon'))
        if amount is None or amount <= 0:
            continue
        slug = str(row.get('slug', ''))
        if not re.fullmatch(r'[A-Za-z0-9]+-\d+', slug):
            continue
        state = states.get(market, {})
        fetched = stamp(row.get('seenAt')) or stamp(state.get('fetchedAt'))
        # A cached index never establishes that an item can still be bought now.
        offer = Offer(slug, payload.get('gift') or query.collection, int(row.get('number') or slug.rsplit('-', 1)[1]),
                      market, amount, currency, str(row.get('model') or ''), str(row.get('backdrop') or ''),
                      str(row.get('symbol') or ''), safe_url(row.get('link', '')),
                      f'https://t.me/nft/{slug}', safe_url(row.get('thumb', ''), media=True),
                      'browse.tg', fetched, bool(row.get('stale')) or state.get('state') != 'ok' or not fetched,
                      bool(row.get('locked')), bool(row.get('preMarket')), colors=row.get('colors') or {})
        if query.matches(offer):
            result.offers.append(offer)
    if payload.get('capped'):
        result.warnings.append(tr('index_limited'))
    return result


def index_search(query: SearchQuery, cancelled=None) -> SearchResult:
    result = SearchResult()
    result.progress={'pages':0}
    # The public endpoint accepts one trait value per query. OR choices are merged locally.
    options = itertools.product(query.models or ('',), query.backdrops or ('',), query.symbols or ('',))
    for model, backdrop, symbol in options:
        if cancelled and cancelled.is_set():
            return result
        params = {'gift': query.collection, 'sort': 'cheapest', 'market': ','.join(query.markets)}
        if query.number is not None:
            params['slug'] = f'{compact(query.collection)}-{query.number}'
        for key, value in (('model', model), ('backdrop', backdrop), ('symbol', symbol)):
            if value:
                params[key] = value
        payload = request('GET', 'https://browse.tg/api/listings', params=params).json()
        result.progress['pages']+=1
        parsed = parse_index(payload, query)
        result.offers = merge_offers(result.offers, parsed.offers)
        result.statuses.extend(parsed.statuses)
        result.warnings.extend(parsed.warnings)
    return result


_portals_collections = None
_portals_lock = threading.Lock()


def portals_catalog():
    global _portals_collections
    with _portals_lock:
        if _portals_collections is None:
            _portals_collections = request('GET','https://portal-market.com/api/collections',params={'offset':0,'limit':200}).json()
        return _portals_collections


def portals_search(query: SearchQuery, offset: int = 0, cancelled=None) -> SearchResult:
    if cancelled and cancelled.is_set():
        return SearchResult()
    params = {'offset': offset, 'limit': 50, 'sort_by': 'price desc' if query.sort_mode == 'price_desc' else 'price asc', 'status': 'listed'}
    if query.collection:
        # Public collections metadata supplies the marketplace's own collection ID.
        data = portals_catalog()
        collection = next((x for x in data.get('collections', []) if compact(x.get('name', '')) == compact(query.collection)), None)
        if not collection:
            return SearchResult(statuses=[SourceStatus('portals', 'no_match', source='direct', complete=True,
                                                       checked_at=time.time(), note=tr('no_collection_source'))])
        params['collection_ids'] = collection['id']
    if cancelled and cancelled.is_set():
        return SearchResult()
    for key, values in (('filter_by_models', query.models), ('filter_by_backdrops', query.backdrops), ('filter_by_symbols', query.symbols)):
        if values:
            params[key] = ','.join(values)
    if query.number is not None:
        params['search'] = str(query.number)
    response = request('GET', 'https://portal-market.com/api/nfts/search', params=params).json()
    rows = response.get('results')
    if not isinstance(rows, list):
        raise ValueError('portals shape')
    now = time.time()
    result = SearchResult()
    for row in rows:
        if row.get('status') != 'listed' or row.get('bundle_id'):
            continue
        attrs = {a.get('type'): a.get('value', '') for a in row.get('attributes', [])}
        slug = str(row.get('tg_id', ''))
        amount = number(row.get('price'))
        if not re.fullmatch(r'[A-Za-z0-9]+-\d+', slug) or amount is None or amount <= 0:
            continue
        # Plain gift links open the gift itself; exact offer deep links use Portals' public item ID.
        item_id = str(row.get('id', ''))
        link = f'https://t.me/portals_market_bot/market?startapp=gift_{item_id}' if re.fullmatch('[A-Za-z0-9-]+', item_id) else ''
        offer = Offer(slug, str(row.get('name', query.collection)), int(row.get('external_collection_number') or slug.rsplit('-', 1)[1]),
                      'portals', amount, 'TON', attrs.get('model', ''), attrs.get('backdrop', ''), attrs.get('symbol', ''),
                      link, f'https://t.me/nft/{slug}', safe_url(row.get('photo_url', ''), True), 'direct', now)
        if query.matches(offer):
            result.offers.append(offer)
    has_more = len(rows) == 50
    result.statuses.append(SourceStatus('portals', 'ok' if result.offers else 'no_match', len(result.offers), now,
                                       not has_more and offset == 0, 'direct',
                                       tr('source_direct')+' · Portals. '+tr('fees_excluded') + (' '+tr('one_page') if has_more else ''), has_more))
    if has_more:
        result.cursors.append({'provider': 'portals', 'query': asdict(query), 'offset': offset + 50})
    return result


def fragment_detail(html: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    attributes = {}
    for row in soup.select('tr'):
        cells = row.select('.table-cell')
        if not cells:
            continue
        key = cells[0].get_text(' ', strip=True)
        if key in ('Model', 'Backdrop', 'Symbol'):
            value = row.select_one('.table-cell-value-link')
            if value:
                attributes[key.lower()] = value.get_text(' ', strip=True)
        if key == 'Model':
            percent = re.search(r'([\d.]+)%', row.get_text(' ', strip=True))
            if percent:
                attributes['rarity'] = number(percent[1])
    button = next((b for b in soup.select('button') if re.match(r'^Buy for ', b.get_text(' ', strip=True))), None)
    attributes['buyable'] = button is not None
    if button:
        attributes['amount'] = number(button.get_text(' ', strip=True).replace('Buy for ', ''))
    return attributes


def fragment_search(query: SearchQuery, known: dict[str, Offer], offset: str = '', cancelled=None, context=None) -> SearchResult:
    if cancelled and cancelled.is_set():
        return SearchResult()
    params = {'filter': 'sale', 'sort': 'price_desc' if query.sort_mode == 'price_desc' else 'price_asc'}
    for attr, values in (('Model', query.models), ('Backdrop', query.backdrops), ('Symbol', query.symbols)):
        if values:
            params[f'attr[{attr}]'] = json.dumps(list(values), ensure_ascii=False)
    if query.number is not None:
        params['query'] = str(query.number)
    url = 'https://fragment.com/gifts/' + compact(query.collection)
    manager = nullcontext(context.setdefault('session',requests.Session())) if context is not None else requests.Session()
    with manager as session:
        html = context['first_html'] if offset and context is not None and context.get('first_html') else request('GET', url, session, params=params).text
        if context is not None:
            context['first_html'] = html
        if cancelled and cancelled.is_set():
            return SearchResult()
        soup = BeautifulSoup(html, 'html.parser')
        collection_field = soup.select_one('input[name="collection"]')
        filter_field = soup.select_one('input[name="filter"]')
        if not collection_field or collection_field.get('value') != compact(query.collection) or not filter_field or filter_field.get('value') != 'sale':
            raise ValueError('fragment search shape')
        if offset:
            match = re.search(r'"apiUrl"\s*:\s*("(?:[^"\\]|\\.)*")', html)
            if not match:
                match = re.search(r'apiUrl\s*:\s*("(?:[^"\\]|\\.)*")', html)
            if not match:
                raise ValueError('fragment paging unavailable')
            api_url = urljoin('https://fragment.com', json.loads(match[1]))
            if not api_url.startswith('https://fragment.com/api?'):
                raise ValueError('fragment api host')
            form = {'type': 'gifts', 'collection': compact(query.collection), 'view': '', **params,
                    'offset_id': offset, 'method': 'searchAuctions'}
            data = request('POST', api_url, session, data=form).json()
            if not data.get('ok'):
                raise ValueError('fragment paging failed')
            soup = BeautifulSoup(data.get('html') or (data.get('body', '') + data.get('foot', '')), 'html.parser')
        cards = soup.select('a.tm-grid-item')
        next_node = soup.select_one('.js-load-more[data-next-offset]')
        next_offset = next_node.get('data-next-offset', '') if next_node else ''
        now = time.time()
        candidates = []
        for card in cards:
            status = card.select_one('.tm-grid-item-status')
            price = card.select_one('.tm-grid-item-value.icon-ton')
            href = card.get('href', '').split('?', 1)[0]
            slug = href.removeprefix('/gift/')
            if not status or status.get_text(' ', strip=True) != 'For sale' or not price:
                continue
            if not re.fullmatch(r'[a-z0-9]+-\d+', slug):
                continue
            amount = number(price.get_text(' ', strip=True))
            if amount is None or amount <= 0:
                continue
            candidates.append((slug, amount))

        def make_offer(candidate):
            if cancelled and cancelled.is_set():
                return None
            slug, amount = candidate
            cached = known.get(norm(slug))
            if cached and cached.model and cached.backdrop and cached.symbol:
                attrs = {'model': cached.model, 'backdrop': cached.backdrop, 'symbol': cached.symbol, 'rarity': cached.rarity}
            else:
                detail_html = request('GET', f'https://fragment.com/gift/{slug}').text
                attrs = fragment_detail(detail_html)
                if not attrs.get('buyable'):
                    return None
                amount = attrs.get('amount') or amount
            offer = Offer(slug, query.collection, int(slug.rsplit('-', 1)[1]), 'fragment', amount, 'TON',
                          attrs.get('model', ''), attrs.get('backdrop', ''), attrs.get('symbol', ''),
                          f'https://fragment.com/gift/{slug}', f'https://t.me/nft/{slug}',
                          f'https://nft.fragment.com/gift/{slug}.medium.jpg', 'direct', now,
                          rarity=attrs.get('rarity'))
            return offer if query.matches(offer) else None

        result = SearchResult()
        failures = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(make_offer, candidate) for candidate in candidates]
            for future in concurrent.futures.as_completed(futures):
                try:
                    offer = future.result()
                    if offer:
                        result.offers.append(offer)
                except (requests.RequestException, ValueError):
                    failures += 1
        complete = not next_offset and not failures and not offset
        state = 'partial' if failures else 'ok' if result.offers else 'no_match'
        result.statuses.append(SourceStatus('fragment', state, len(result.offers), now, complete, 'direct',
                                           tr('source_direct')+' · Fragment. '+tr('fees_excluded') +
                                           (' '+tr('data_incomplete')+' ('+str(failures)+')' if failures else ''), bool(next_offset)))
        if next_offset:
            result.cursors.append({'provider': 'fragment', 'query': asdict(query), 'offset': next_offset})
        return result


from .catalogue import Catalog, query_from_dict
from .cache import ListingCache


class SearchEngine:
    def __init__(self,catalog):
        self.catalog=catalog
        self.cache=ListingCache(catalog.directory) if hasattr(catalog,'directory') else None

    def cached(self,query):
        queries,scope=self.catalog.resolve(query)
        result=self.cache.find(queries) if self.cache else SearchResult()
        result.scope=scope
        return result

    def search(self,query,progress=lambda _:None,cancelled=None,on_update=None,auto_pages=True):
        cancelled=cancelled or threading.Event()
        queries,scope=self.catalog.resolve(query)
        if not queries:
            raise ValueError(tr('err_models'))
        result=self.cache.find(queries) if self.cache else SearchResult()
        result.scope=scope
        known=self.cache.known_traits() if self.cache else {norm(o.slug):o for o in result.offers}
        complete=[]
        contexts={}
        page_keys={}
        partial_scopes=set()
        source_status={}
        visited=set()
        walks={(q,m) for q in queries for m in ('index','fragment','portals') if m=='index' or m in q.markets}
        closed=set();pages=0;failed=set()
        def progress_data(phase='searching'):
            return {'phase':phase,'checked':len(closed),'total':len(walks),'pages':pages,'errors':len(failed)}
        def publish():
            result.statuses=list(source_status.values())
            result.progress=progress_data()
            if on_update:
                on_update(SearchResult(list(result.offers),list(result.statuses),list(result.cursors),list(dict.fromkeys(result.warnings)),scope,dict(result.progress)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pending={}
            def submit(q,market,offset=None):
                key=(q,market)
                if market=='index':
                    future=pool.submit(index_search,q,cancelled=cancelled)
                elif market=='fragment':
                    context=contexts.setdefault(key,{})
                    future=pool.submit(fragment_search,q,known,offset=offset or '',cancelled=cancelled,context=context)
                else:
                    future=pool.submit(portals_search,q,offset=offset or 0,cancelled=cancelled)
                pending[future]=(q,market)
            for q in queries:
                submit(q,'index')
                for market in ('fragment','portals'):
                    if market in q.markets:
                        submit(q,market)
            publish()
            while pending:
                if cancelled.is_set():
                    break
                finished,_=concurrent.futures.wait(pending,timeout=.15,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in finished:
                    q,market=pending.pop(future)
                    key=(q,market)
                    try:
                        incoming=future.result()
                    except Exception as error:
                        closed.add(key);failed.add(key)
                        partial_scopes.add(key)
                        for m in q.markets if market=='index' else (market,):
                            source_status[(q,m,market)]=SourceStatus(m,'unavailable',source='browse.tg' if market=='index' else 'direct',note=error_note(error))
                        publish();continue
                    if cancelled.is_set():
                        break
                    pages+=incoming.progress.get('pages',1)
                    if not incoming.cursors:closed.add(key)
                    if any(s.state in ('unavailable','partial','error') for s in incoming.statuses):failed.add(key)
                    if hasattr(self.catalog,'enrich'):
                        incoming.offers=[self.catalog.enrich(o) for o in incoming.offers]
                    native=market!='index'
                    if native:
                        page_keys.setdefault(key,set()).update(o.key for o in incoming.offers)
                        if not incoming.statuses or any(s.state not in ('ok','no_match') for s in incoming.statuses):
                            partial_scopes.add(key)
                            result.warnings.append(MARKETS[market][0]+': '+tr('data_incomplete'))
                        is_complete=bool(key not in partial_scopes and incoming.statuses and not incoming.cursors)
                        if is_complete:
                            present=page_keys[key]
                            complete.append((q,market,present))
                            result.offers=[o for o in result.offers if not (o.market==market and q.matches(o) and o.key not in present)]
                            if self.cache:
                                self.cache.remove_absent(q,market,present)
                        for status in incoming.statuses:
                            status.count=len(page_keys[key]);status.complete=is_complete
                            if key in partial_scopes:
                                status.state='partial';status.note+=' '+tr('data_incomplete')
                    # An index that answers late must not re-add a sold listing
                    # invalidated by a fully traversed direct source.
                    incoming.offers=[o for o in incoming.offers if not any(o.source!='direct' and o.market==m and cq.matches(o) and o.key not in ids for cq,m,ids in complete)]
                    result.offers=merge_offers(result.offers,incoming.offers)
                    known.update({norm(o.slug):o for o in incoming.offers})
                    if self.cache:
                        self.cache.save(incoming.offers)
                    for status in incoming.statuses:
                        source_status[(q,status.market,market)]=status
                    result.warnings.extend(incoming.warnings)
                    for cursor in incoming.cursors:
                        signature=(q,market,str(cursor['offset']))
                        if signature in visited:
                            closed.add(key);failed.add(key)
                            result.warnings.append(MARKETS[market][0]+': '+tr('source_repeat'))
                            continue
                        visited.add(signature)
                        if auto_pages and not cancelled.is_set():
                            submit(q,market,cursor['offset'])
                        else:
                            result.cursors.append(cursor)
                    progress(scope+' · '+tr('loading_offers',count=len(result.offers)) + (' · '+tr('more_pages') if pending else ''))
                    publish()
        for context in contexts.values():
            if context.get('session'):
                context['session'].close()
        result.statuses=list(source_status.values())
        result.warnings=list(dict.fromkeys(result.warnings))
        result.progress=progress_data('stopped' if cancelled.is_set() else 'complete' if closed==walks else 'partial')
        return result

    def more(self,cursors,known,cancelled=None):
        result=SearchResult()
        for cursor in cursors:
            if cancelled and cancelled.is_set():break
            q=query_from_dict(cursor['query'])
            batch=fragment_search(q,known,cursor['offset'],cancelled) if cursor['provider']=='fragment' else portals_search(q,cursor['offset'],cancelled)
            result.offers=merge_offers(result.offers,batch.offers)
            result.statuses.extend(batch.statuses);result.cursors.extend(batch.cursors)
        return result
