import copy
from dataclasses import asdict
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtWidgets import QApplication, QListWidget

from giftfinder.core import SearchQuery
from giftfinder.design import MotionButton
from giftfinder.i18n import tr
from giftfinder.ui import MainWindow
from giftfinder.ui_common import application


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path / 'profile'))
    window = MainWindow(offline=True)
    yield window
    window.close(); app.processEvents()


@pytest.mark.parametrize('language', ['en', 'ru', 'ar'])
def test_saved_query_labels_identify_number_symbols_market_and_price_without_changing_data(window, app, language):
    window.change_language(language)
    symbols = [row['name'] for row in window.catalog.symbol_rows if row['collection'] == 'Easter Egg'][:2]
    assert len(symbols) == 2
    for number, market, minimum, maximum, currency, symbol in [
        (1, 'fragment', '1', '10', 'USD', symbols[0]),
        (2, 'portals', '1000', '2000', 'RUB', symbols[1]),
    ]:
        window.filter_query = SearchQuery(collection='Easter Egg', number=number, markets=(market,), symbols=(symbol,))
        window.filter_extra = {'min': minimum, 'max': maximum, 'unit': currency}
        window.save_search()
    before = copy.deepcopy(window.store.data['searches'])
    window.saved_searches(); app.processEvents()
    dialog = window.dialogs[-1]
    items = dialog.findChild(QListWidget)
    titles = [items.item(i).text() for i in range(items.count())]
    assert len(titles) == 2 and titles[0] != titles[1]
    assert all(tr(key)+':' in title for key in ('number','symbol','market','price') for title in titles)
    assert 'Fragment' in titles[0] and '1–10 USD' in titles[0] and symbols[0] in titles[0]
    assert 'Portals' in titles[1] and '1000–2000 RUB' in titles[1] and symbols[1] in titles[1]
    assert window.store.data['searches'] == before
    calls = []
    window.start_search = lambda: calls.append((window.current_query(), dict(window.filter_extra)))
    items.setCurrentRow(1)
    next(button for button in dialog.findChildren(MotionButton) if button.text() == tr('open_search')).click()
    assert calls == [(SearchQuery(collection='Easter Egg', number=2, markets=('portals',), symbols=(symbols[1],)),
                      {'min':'1000','max':'2000','unit':'RUB'})]
    assert window.store.data['searches'] == before


def test_legacy_saved_price_caption_uses_same_fields_as_loading_without_migrating_profile(window, app):
    window.change_language('en')
    query = SearchQuery(collection='Easter Egg', number=42, markets=('fragment',))
    legacy = {**asdict(query), 'price_min':'2.5', 'price_max':'', 'price_currency':'TON'}
    window.store.data['searches'] = [legacy]
    before = copy.deepcopy(window.store.data['searches'])
    window.saved_searches(); app.processEvents()
    dialog = window.dialogs[-1]
    items = dialog.findChild(QListWidget)
    assert '2.5–∞ GRAM' in items.item(0).text()
    calls = []
    window.start_search = lambda: calls.append((window.current_query(), dict(window.filter_extra)))
    items.setCurrentRow(0)
    next(button for button in dialog.findChildren(MotionButton) if button.text() == tr('open_search')).click()
    assert calls == [(query, {'min':'2.5','max':'','unit':'TON'})]
    assert window.store.data['searches'] == before


def test_equal_target_counts_show_actual_models_and_full_tooltip_without_changing_loading(window, app):
    window.change_language('en')
    queries = [SearchQuery(collection='Input Key', targets=(('Input Key', name),)) for name in ('Creeper','Telegram')]
    for query in queries:
        window.filter_query = query
        window.save_search()
    before = copy.deepcopy(window.store.data['searches'])
    window.saved_searches(); app.processEvents()
    dialog = window.dialogs[-1]
    items = dialog.findChild(QListWidget)
    titles = [items.item(i).text() for i in range(items.count())]
    assert titles[0] != titles[1]
    assert 'Model: Creeper' in titles[0] and 'Model: Telegram' in titles[1]
    assert all(items.item(i).toolTip() == title for i,title in enumerate(titles))
    assert window.store.data['searches'] == before
    calls = []
    window.start_search = lambda: calls.append(window.current_query())
    items.setCurrentRow(1)
    next(button for button in dialog.findChildren(MotionButton) if button.text() == tr('open_search')).click()
    assert calls == [queries[1]] and window.store.data['searches'] == before


def test_cross_collection_target_caption_includes_each_collection(window, app):
    window.change_language('en')
    query = SearchQuery(targets=(('Input Key','Creeper'),('Easter Egg','Creeper')))
    window.filter_query = query; window.save_search()
    window.saved_searches(); app.processEvents()
    item = window.dialogs[-1].findChild(QListWidget).item(0)
    assert 'Input Key / Creeper' in item.text() and 'Easter Egg / Creeper' in item.text()
    assert item.toolTip() == item.text()
