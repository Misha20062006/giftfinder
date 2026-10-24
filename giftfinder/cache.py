from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .core import Offer, SearchResult, SourceStatus


class ListingCache:
    def __init__(self, directory: Path):
        self.path = directory / 'market-cache.sqlite3'
        directory.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS offers (key TEXT PRIMARY KEY, collection TEXT, slug TEXT,
                    market TEXT, observed REAL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS offers_collection ON offers(collection);
                CREATE TABLE IF NOT EXISTS traits (slug TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS scopes (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def save(self, offers):
        with self.connection() as db:
            for offer in offers:
                payload = json.dumps(offer.to_dict(), ensure_ascii=False)
                old = db.execute('SELECT observed,payload FROM offers WHERE key=?', (offer.key,)).fetchone()
                previous = json.loads(old[1]) if old else {}
                preferred = offer.source == 'direct' and previous.get('source') != 'direct'
                keeps_direct = previous.get('source') == 'direct' and offer.source != 'direct'
                if old is None or preferred or (not keeps_direct and (offer.checked_at or 0) >= (old[0] or 0)):
                    db.execute('INSERT OR REPLACE INTO offers VALUES (?,?,?,?,?,?)',
                               (offer.key, offer.collection, offer.slug.casefold(), offer.market, offer.checked_at, payload))
                if offer.model and offer.backdrop and offer.symbol:
                    db.execute('INSERT OR REPLACE INTO traits VALUES (?,?)', (offer.slug.casefold(), payload))

    def known_traits(self):
        with self.connection() as db:
            rows = db.execute('SELECT slug,payload FROM traits').fetchall()
        return {slug:Offer.from_dict(json.loads(raw)) for slug,raw in rows}

    def remove_absent(self, query, market, present_keys):
        """Only a fully traversed direct search can invalidate older listings."""
        with self.connection() as db:
            rows = db.execute('SELECT key,payload FROM offers WHERE collection=? AND market=?', (query.collection,market)).fetchall()
            for key,raw in rows:
                if key not in present_keys and query.matches(Offer.from_dict(json.loads(raw))):
                    db.execute('DELETE FROM offers WHERE key=?', (key,))

    def find(self, queries):
        collections = list(dict.fromkeys(q.collection for q in queries))
        if not collections:
            return SearchResult()
        marks = ','.join('?' for _ in collections)
        with self.connection() as db:
            raw_rows = db.execute(f'SELECT payload FROM offers WHERE collection IN ({marks})', collections).fetchall()
        result = SearchResult()
        for raw, in raw_rows:
            try:
                offer = Offer.from_dict(json.loads(raw))
                if any(q.matches(offer) for q in queries):
                    offer.source = 'local-cache'
                    offer.stale = True
                    result.offers.append(offer)
            except (ValueError,TypeError):
                continue
        for market in dict.fromkeys(o.market for o in result.offers):
            rows = [o for o in result.offers if o.market == market]
            result.statuses.append(SourceStatus(market,'stale',len(rows),min(o.checked_at or 0 for o in rows),False,'local-cache',
                                               'Сохранённые предложения. Обновление выполняется в фоне.'))
        return result
