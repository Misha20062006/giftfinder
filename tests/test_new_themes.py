"""Reviewed groups must resolve exact pairs and never grow from name guesses."""
import pytest

from giftfinder.catalogue import Catalog
from giftfinder.core import SearchQuery
from giftfinder.i18n import LANGUAGES, set_language, theme_name, translations

COUNTS = {'pepe':32, 'gold':24, 'silver':8, 'star_wars':10, 'harry_potter':8,
          'pokemon':6, 'sailor_moon':6, 'doge':7, 'space':9}


@pytest.mark.parametrize('key,count', COUNTS.items())
def test_new_theme_resolves_every_reviewed_pair_locally_and_keeps_other_filters(tmp_path, key, count):
    catalog = Catalog(tmp_path)
    members = set(catalog.themes[key]['members'])
    assert len(members) == count
    variants, _ = catalog.resolve(SearchQuery(theme=key, backdrops=('Black',), markets=('fragment',)))
    assert {(v.collection,m) for v in variants for m in v.models} == members
    assert all(v.backdrops == ('Black',) and v.markets == ('fragment',) for v in variants)
    first_collection, first_model = next(iter(members))
    scoped, _ = catalog.resolve(SearchQuery(collection=first_collection, theme=key))
    assert all(v.collection == first_collection for v in scoped)
    assert first_model in {m for v in scoped for m in v.models}


def test_false_positive_names_and_cross_collection_pairs_are_not_members(tmp_path):
    catalog = Catalog(tmp_path)
    assert ('Stellar Rocket','Pepelatz') not in catalog.themes['pepe']['members']
    assert ('Hypno Lollipop','Amphibian') not in catalog.themes['pepe']['members']
    assert ('Mini Oscar','Android') not in catalog.themes['star_wars']['members']
    assert ('Sakura Flower','Pokerface') not in catalog.themes['pokemon']['members']
    assert ('Artisan Brick','Poker Chips') not in catalog.themes['pokemon']['members']
    assert ('Loot Bag','Pepe Bag') in catalog.themes['pepe']['members']
    assert ('Joyful Bundle','Pepe Bag') in catalog.themes['pepe']['members']
    catalog.data['traits']['Easter Egg']['models'].append({'name':'Golden Pepe Pikachu'})
    catalog.reindex()
    for key in ('pepe','gold','pokemon'):
        assert ('Easter Egg','Golden Pepe Pikachu') not in catalog.themes[key]['members']


def test_new_theme_names_are_bundled_in_all_languages_and_english_fallback_works():
    try:
        for code in LANGUAGES:
            set_language(code)
            for key in COUNTS:
                assert 'theme_'+key in translations(code)
                assert theme_name(key) and not theme_name(key).startswith('theme_')
        set_language('ru')
        assert theme_name('gold') == 'Золотые'
        set_language('en')
        assert theme_name('pepe') == 'Pepe' and theme_name('space') == 'Space'
    finally:
        set_language('ru')
