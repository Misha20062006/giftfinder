from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlparse

MARKETS = {
    'fragment': ('Fragment', '#8ea8d0'),
    'portals': ('Portals', '#ac92f5'),
    'telegram': ('Telegram', '#6ab8fa'),
    'getgems': ('Getgems', '#63d3ae'),
    'mrkt': ('MRKT', '#edbc73'),
    'tonnel': ('Tonnel', '#ed8da8'),
}


def number(value) -> Decimal | None:
    if value is None or value == '' or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace('\u00a0', '').replace(' ', '').replace(',', ''))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, ValueError):
        return None


def norm(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value).replace('’', "'").replace('‘', "'")).strip().casefold()


def compact(value: str) -> str:
    return re.sub('[^a-z0-9]', '', norm(value))


@lru_cache(maxsize=65536)
def offer_key(market,slug):
    return f'{market}:{norm(slug)}'


def safe_url(value: str, media: bool = False) -> str:
    """Only marketplace links and the observed public image hosts are accepted."""
    try:
        parsed = urlparse(str(value))
        hosts = {'fragment.com', 'www.fragment.com', 't.me', 'telegram.me', 'getgems.io',
                 'portal-market.com', 'portals-market.com', 'market.tonnel.network', 'browse.tg'}
        if media:
            hosts |= {'nft.fragment.com', 'api.changes.tg', 'cdn.changes.tg',
                      'storage.googleapis.com', 'gifts.coffin.meme', 'i.getgems.io'}
        if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password:
            return ''
        if parsed.port not in (None, 443):
            return ''
        return str(value)
    except (ValueError, TypeError):
        return ''


def stamp(value) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, TypeError):
        return None


def age_label(value: float | None) -> str:
    if not value:
        return 'время источника неизвестно'
    age = max(0, time.time() - value)
    if age < 60:
        return 'только что'
    if age < 3600:
        return f'{int(age / 60)} мин назад'
    if age < 86400:
        return f'{int(age / 3600)} ч назад'
    return f'{int(age / 86400)} дн назад'


def fmt(value: Decimal | None, digits: int = 2) -> str:
    if value is None:
        return '—'
    return f'{value:,.{digits}f}'.replace(',', ' ').rstrip('0').rstrip('.') if digits else f'{value:,.0f}'.replace(',', ' ')


@dataclass(frozen=True)
class SearchQuery:
    collection: str = ''
    models: tuple[str, ...] = ()
    backdrops: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    number: int | None = None
    text: str = ''
    markets: tuple[str, ...] = tuple(MARKETS)
    theme: str = ''
    targets: tuple[tuple[str, str], ...] = ()
    sort_mode: str = 'price_asc'
    monochrome: bool = False
    mono_colors: tuple[str, ...] = ()

    def matches(self, offer: Offer) -> bool:
        if self.monochrome or self.mono_colors:
            from .monochrome import allowed
            if not allowed(offer.collection,offer.model,offer.backdrop,self.mono_colors):return False
        if self.collection and compact(self.collection) != compact(offer.collection):
            return False
        if self.targets and (compact(offer.collection), norm(offer.model)) not in {(compact(c), norm(m)) for c, m in self.targets}:
            return False
        for values, actual in ((self.models, offer.model), (self.backdrops, offer.backdrop), (self.symbols, offer.symbol)):
            if values and norm(actual) not in {norm(x) for x in values}:
                return False
        return (self.number is None or self.number == offer.number) and offer.market in self.markets


@dataclass
class Offer:
    slug: str
    collection: str
    number: int
    market: str
    amount: Decimal | None
    currency: str
    model: str = ''
    backdrop: str = ''
    symbol: str = ''
    link: str = ''
    telegram_url: str = ''
    image: str = ''
    source: str = 'browse.tg'
    checked_at: float | None = None
    stale: bool = False
    locked: bool = False
    premarket: bool = False
    rarity: Decimal | None = None
    colors: dict = field(default_factory=dict)
    price_note: str = 'Цена объявления. Комиссии площадки могут добавляться.'

    @property
    def key(self) -> str:
        return offer_key(self.market,self.slug)

    @property
    def price_label(self) -> str:
        return f'{fmt(self.amount, 0 if self.currency == "Stars" else 2)} {"GRAM" if self.currency in ("TON", "GRAM") else self.currency}'

    def to_dict(self) -> dict:
        data = asdict(self)
        data['amount'] = str(self.amount) if self.amount is not None else None
        data['rarity'] = str(self.rarity) if self.rarity is not None else None
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Offer:
        clean = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        clean['amount'] = number(clean.get('amount'))
        clean['rarity'] = number(clean.get('rarity'))
        clean['link'] = safe_url(clean.get('link', ''))
        clean['telegram_url'] = safe_url(clean.get('telegram_url', ''))
        clean['image'] = safe_url(clean.get('image', ''), media=True)
        return cls(**clean)


@dataclass
class SourceStatus:
    market: str
    state: str
    count: int = 0
    checked_at: float | None = None
    complete: bool = False
    source: str = 'browse.tg'
    note: str = ''
    has_more: bool = False


@dataclass
class SearchResult:
    offers: list[Offer] = field(default_factory=list)
    statuses: list[SourceStatus] = field(default_factory=list)
    cursors: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    scope: str = ''
    progress: dict = field(default_factory=dict)


def ton_value(offer: Offer, rub_per_ton: Decimal | None, rub_per_star: Decimal | None) -> Decimal | None:
    if offer.amount is None:
        return None
    if offer.currency in ('TON', 'GRAM'):
        return offer.amount
    if offer.currency == 'Stars' and rub_per_ton and rub_per_star:
        return offer.amount * rub_per_star / rub_per_ton
    return None


def rub_value(offer: Offer, rub_per_ton: Decimal | None, rub_per_star: Decimal | None) -> Decimal | None:
    rate = rub_per_ton if offer.currency in ('TON', 'GRAM') else rub_per_star if offer.currency == 'Stars' else None
    return offer.amount * rate if offer.amount is not None and rate else None


def sorted_offers(offers: list[Offer], mode='price_asc', rub_per_ton=None, rub_per_star=None) -> list[Offer]:
    if mode in ('price_asc', 'price_desc'):
        def key(o):
            price = ton_value(o, rub_per_ton, rub_per_star)
            if price is None:
                return (1, o.currency, -(o.amount or Decimal(0)) if mode == 'price_desc' else o.amount or Decimal(0), o.key)
            return (0, '', -price if mode == 'price_desc' else price, o.key)
        return sorted(offers, key=key)
    if mode == 'number':
        return sorted(offers, key=lambda o: (o.number, o.collection, o.key))
    if mode == 'fresh':
        return sorted(offers, key=lambda o: (o.stale, -(o.checked_at or 0), o.key))
    if mode == 'rarity':
        return sorted(offers, key=lambda o: (o.rarity is None, o.rarity or Decimal(0), o.key))
    return list(offers)


def merge_offers(existing: list[Offer], incoming: list[Offer]) -> list[Offer]:
    data = {o.key: o for o in existing}
    for item in incoming:
        old = data.get(item.key)
        if old is None or (item.source == 'direct' and old.source != 'direct') or (
            (item.source == old.source or (old.source == 'local-cache' and item.source != 'local-cache'))
            and (item.checked_at or 0) >= (old.checked_at or 0)
        ):
            data[item.key] = item
    return list(data.values())


def csv_text(offers: list[Offer], rub_per_ton=None, rub_per_star=None) -> str:
    out = io.StringIO(newline='')
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['Коллекция', 'Номер', 'Модель', 'Фон', 'Узор', 'Площадка', 'Цена', 'Валюта',
                     'Примерно ₽', 'Источник', 'Время источника UTC', 'Данные устарели', 'Ссылка'])
    def cell(value):
        text = str(value)
        return "'" + text if text.lstrip()[:1] in ('=', '+', '-', '@') else text
    for o in offers:
        writer.writerow([cell(o.collection), o.number, cell(o.model), cell(o.backdrop), cell(o.symbol),
                         MARKETS[o.market][0], str(o.amount or ''), 'GRAM' if o.currency in ('TON', 'GRAM') else o.currency,
                         str(rub_value(o, rub_per_ton, rub_per_star) or ''), o.source,
                         time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(o.checked_at)) if o.checked_at else '',
                         'да' if o.stale else 'нет', o.link])
    return out.getvalue()


class Store:
    """App-owned preferences only; no access to existing Telegram/browser profiles."""
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / 'preferences.json'
        self.data = {'favorites': {}, 'searches': [], 'settings': {}}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    for key, default in self.data.items():
                        if isinstance(data.get(key), type(default)):
                            self.data[key] = data[key]
            except (OSError, ValueError):
                pass

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)

    def toggle(self, offer: Offer):
        favorites = self.data['favorites']
        if offer.key in favorites:
            del favorites[offer.key]
        else:
            favorites[offer.key] = offer.to_dict()
        self.save()

    def favorites(self) -> list[Offer]:
        items = []
        for row in self.data['favorites'].values():
            try:
                offer = Offer.from_dict(row)
                offer.stale = True
                items.append(offer)
            except (TypeError, ValueError):
                continue
        return items
