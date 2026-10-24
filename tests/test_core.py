from decimal import Decimal

from giftfinder.core import (Offer, SearchQuery, SourceStatus, Store, csv_text,
                             merge_offers, number, safe_url, sorted_offers, ton_value)


def offer(**kwargs):
    fields = dict(slug='EasterEgg-42', collection='Easter Egg', number=42,
                  market='portals', amount=Decimal('10.50'), currency='TON',
                  model='Creeper', backdrop='Black', symbol='Bread')
    fields.update(kwargs)
    return Offer(**fields)


def test_exact_backdrop_and_or_models():
    q = SearchQuery(collection='Easter Egg', models=('Creeper', 'Chicken'), backdrops=('Black',))
    assert q.matches(offer())
    assert q.matches(offer(model='Chicken'))
    assert not q.matches(offer(backdrop='Onyx Black'))
    assert not q.matches(offer(model='Creeper Berry'))
    assert not q.matches(offer(collection='Input Key'))


def test_price_precision_and_invalid_prices():
    assert number('0.123456789') == Decimal('0.123456789')
    for value in ('NaN', 'Infinity', '-1', True, '', None, 'not a price'):
        assert number(value) is None


def test_stars_never_sorted_as_zero_ton():
    stars = offer(slug='EasterEgg-43', currency='Stars', amount=Decimal('1'))
    ton = offer(amount=Decimal('10'))
    assert sorted_offers([stars, ton]) == [ton, stars]
    assert sorted_offers([stars, ton], 'price_desc') == [ton, stars]
    assert ton_value(stars, Decimal('100'), None) is None
    assert ton_value(stars, Decimal('100'), Decimal('2')) == Decimal('0.02')
    assert sorted_offers([ton, stars], 'price_asc', Decimal('100'), Decimal('2')) == [stars, ton]


def test_numeric_sort_not_lexicographic():
    a, b = offer(amount=Decimal('9.99')), offer(slug='EasterEgg-43', amount=Decimal('100'))
    assert sorted_offers([b, a]) == [a, b]
    assert sorted_offers([a, b], 'price_desc') == [b, a]


def test_cache_cannot_overwrite_fresh_direct_answer():
    live = offer(source='direct', checked_at=100, amount=Decimal('80'))
    cached = offer(source='browse.tg', checked_at=200, amount=Decimal('199'))
    assert merge_offers([live], [cached]) == [live]
    assert merge_offers([cached], [live]) == [live]
    other_market = offer(market='fragment')
    assert len(merge_offers([live], [other_market])) == 2


def test_link_validation():
    assert safe_url('https://t.me/nft/EasterEgg-42')
    for value in ('javascript:alert(1)', 'https://evil.example/x', 'https://t.me@evil.example/',
                  'https://t.me.evil.example/', 'file:///C:/Windows/notepad.exe', 'https://t.me:444/x'):
        assert not safe_url(value)


def test_favorites_use_app_profile_and_keep_original_price(tmp_path):
    store = Store(tmp_path / 'profile')
    item = offer(link='https://t.me/nft/EasterEgg-42')
    store.toggle(item)
    reopened = Store(tmp_path / 'profile')
    assert reopened.favorites()[0].amount == item.amount
    assert reopened.favorites()[0].stale
    reopened.toggle(item)
    assert not Store(tmp_path / 'profile').favorites()


def test_csv_keeps_original_currency_and_prevents_formula_cells():
    text = csv_text([offer(model='=1+1', currency='Stars', amount=Decimal('888'))])
    assert "'=1+1" in text
    assert ';888;Stars;' in text
    assert 'Примерно ₽' in text
