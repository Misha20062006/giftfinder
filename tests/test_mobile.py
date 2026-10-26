import csv
from dataclasses import replace
from decimal import Decimal
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QListWidget, QMenu

from giftfinder.core import MARKETS, Offer, SearchQuery, Store
from giftfinder.mobile_ui import MobileFilterDialog, MobileWindow
from giftfinder.design import MotionButton
from giftfinder.i18n import tr
from giftfinder.qa import settle
from giftfinder.ui_common import application


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


@pytest.fixture(scope='module')
def touch_device():
    # A real touchscreen outlives its events; destroying Qt's synthetic device
    # while kinetic scrolling is active can synthesize a stray mouse release.
    return QTest.createTouchDevice()


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path / 'profile'))
    window = MobileWindow(offline=True)
    window.change_language('en')
    window.show(); settle(window)
    yield window
    window.close(); window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def inside(window, widget):
    return QRect(window.mapFromGlobal(widget.mapToGlobal(QPoint(0,0))), widget.size())


def offer():
    return Offer('EasterEgg-42', 'Easter Egg', 42, 'fragment', Decimal('1.23456789'),
                 'TON', 'Creeper', 'Black', link='https://fragment.com/gift/EasterEgg-42', source='direct')


@pytest.mark.parametrize('language', ['en', 'ru', 'ar'])
def test_phone_layout_has_reachable_header_search_and_navigation(window, app, language):
    window.change_language(language); settle(window)
    assert window.width() == 360 and window.height() == 800
    for name in ('language_button', 'mobile_menu_button', 'search_edit', 'filter_button', 'find_button', 'nav_catalog', 'nav_favorites', 'mobile_saved_button'):
        widget = getattr(window, name)
        assert widget.isVisible(), name
        assert window.rect().contains(inside(window, widget)), (name, widget.geometry())
        assert widget.height() >= 40
    assert window.home_model.rowCount() == 123 and window.theme_model.rowCount() == len(window.catalog.themes)
    assert window.home_grid.horizontalScrollBar().maximum() == 0
    assert window.theme_grid.verticalScrollBar().maximum() > 0
    assert window.filter_button.accessibleName() == 'Filters'
    assert window.language_button.accessibleIdentifier() == 'mobileLanguageButton'
    assert window.language_button.objectName() == 'select'
    for widget in (window.nav_catalog, window.nav_favorites, window.mobile_saved_button):
        _, height = widget.text_layout(widget.width()-widget.text_space())
        assert height <= widget.height()-4
    assert window.assets.network_started == 0


def test_filter_sheet_exposes_every_category_and_six_markets(window, app):
    window.open_filters(); settle(window)
    dialog = window.filter_dialog
    assert isinstance(dialog, MobileFilterDialog) and dialog.width() == 360
    assert dialog.category_select.accessibleIdentifier() == 'mobileFilterCategory'
    assert dialog.search.accessibleIdentifier() == 'mobileFilterListSearch'
    assert {dialog.category_select.itemData(i) for i in range(dialog.category_select.count())} == {'collections','models','backdrops','symbols','themes','colors'}
    assert set(dialog.market_checks) == set(MARKETS)
    dialog.advanced_toggle.click(); app.processEvents()
    assert dialog.advanced.isVisible()
    for widget in (*dialog.market_checks.values(), dialog.minimum, dialog.maximum, dialog.unit, dialog.number):
        assert widget.isVisible()
        rect = inside(dialog.form_scroll.widget(), widget)
        assert rect.left() >= 0 and rect.right() < dialog.form_scroll.widget().width()
    assert dialog.grid.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize('size', [(640,360),(360,480)])
def test_short_screens_keep_navigation_and_catalog_reachable_without_changing_queries(window, app, size):
    original = SearchQuery(collection='Input Key', models=('Creeper',), mono_colors=('green',), monochrome=True)
    window.filter_query = original; window.filter_extra = {'min':'2','max':'50','unit':'USD'}
    collapsed = window.themes_collapsed
    stored = window.store.data['settings'].get('themes_collapsed')
    window.resize(*size); settle(window)
    assert (window.width(), window.height()) == size
    for name in ('language_button','mobile_menu_button','search_edit','filter_button','find_button','nav_catalog','nav_favorites','mobile_saved_button','home_grid'):
        assert window.rect().contains(inside(window, getattr(window,name))), name
    assert window.home_grid.height() >= 92
    assert not window.theme_grid.isVisible()
    window.theme_toggle.click(); settle(window)
    assert window.filter_dialog.category == 'themes'
    window.filter_dialog.number.setText('123')
    draft = window.filter_dialog.state
    window.resize(360,800); settle(window)
    assert window.filter_dialog.width() == 360 and window.filter_dialog.height() == 800
    assert window.filter_dialog.state == draft and window.filter_dialog.number.text() == '123'
    window.handle_back(); app.processEvents()
    assert window.theme_grid.isVisible() == (not collapsed)
    assert window.themes_collapsed == collapsed
    assert window.store.data['settings'].get('themes_collapsed') == stored
    assert window.filter_query == original
    assert window.filter_extra == {'min':'2','max':'50','unit':'USD'}


def test_phone_filters_keep_multiple_traits_colors_price_currency_number_and_markets(window, app):
    calls = []
    window.start_search = lambda: calls.append(window.current_query())
    query = SearchQuery(collection='Input Key', targets=(('Input Key','Creeper'),('Input Key','Telegram')),
                        backdrops=('Malachite','Sapphire'), monochrome=True)
    window.open_filters('colors', query); dialog = window.filter_dialog
    for color in ('green','blue'):
        row = next(i for i, value in enumerate(dialog.rows.rows) if value['key'] == color)
        dialog.choose(dialog.rows.index(row))
    assert dialog.state.mono_colors == ('green','blue')
    dialog.change_tab('symbols')
    selected = tuple(row['name'] for row in dialog.rows.rows[:2])
    for i in range(2): dialog.choose(dialog.rows.index(i))
    dialog.minimum.setText('5,5'); dialog.maximum.setText('20')
    dialog.unit.setCurrentIndex(dialog.unit.findData('USD')); dialog.number.setText('42')
    for name, check in dialog.market_checks.items(): check.setChecked(name in ('fragment','portals'))
    dialog.apply(); app.processEvents()
    assert len(calls) == 1
    actual = calls[0]
    assert actual.targets == query.targets and actual.backdrops == query.backdrops
    assert actual.symbols == selected and actual.mono_colors == ('green','blue')
    assert actual.number == 42 and actual.markets == ('fragment','portals')
    assert window.filter_extra == {'min':'5,5','max':'20','unit':'USD'}
    assert window.filter_dialog is None


def test_android_back_cancels_filter_draft_and_preserves_active_search(window, app):
    original = SearchQuery(collection='Input Key', models=('Creeper',), backdrops=('Malachite',))
    window.filter_query = original; window.filter_extra = {'min':'10','max':'20','unit':'USD'}
    window.open_filters('models'); dialog = window.filter_dialog
    dialog.minimum.setText('999'); dialog.state = replace(dialog.state, number=123)
    QTest.keyClick(dialog.search, Qt.Key.Key_Back); app.processEvents()
    assert window.filter_dialog is None and window.isVisible()
    assert window.filter_query == original
    assert window.filter_extra == {'min':'10','max':'20','unit':'USD'}


def test_smoke_closed_marker_follows_actual_filter_finished_signal(window, app, monkeypatch, capsys):
    monkeypatch.setenv('GIFT_FINDER_ANDROID_SMOKE', '1')
    window.open_filters(); app.processEvents()
    opened = capsys.readouterr().out
    assert 'GIFTFINDER_ANDROID_FILTERS_OPEN' in opened
    assert 'GIFTFINDER_ANDROID_FILTERS_CLOSED' not in opened
    QTest.keyClick(window.filter_dialog.search, Qt.Key.Key_Back); app.processEvents()
    assert capsys.readouterr().out.count('GIFTFINDER_ANDROID_FILTERS_CLOSED') == 1
    assert window.filter_dialog is None and window.isVisible()


def test_result_details_favorite_link_and_back_return_to_catalog(window, app, monkeypatch):
    item = offer(); window.mode = 'search'; window.offers = [item]; window.render_offers(); settle(window)
    assert window.offer_model.rowCount() == 1
    assert window.view.horizontalScrollBar().maximum() == 0
    window.show_details(window.offer_model.index(0)); settle(window)
    dialog = window.dialogs[-1]
    assert dialog.width() == 360 and dialog.height() == 800
    opened = []; monkeypatch.setattr(QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()) or True)
    dialog.open_button.click()
    assert opened == [item.link]
    dialog.favorite.click()
    assert item.key in Store(window.data_dir).data['favorites']
    window.handle_back(); app.processEvents()
    assert not window.dialogs and window.mode == 'search'
    window.handle_back(); app.processEvents()
    assert window.mode == 'catalog' and window.isVisible()
    window.show_favorites()
    assert window.offer_model.rowCount() == 1


def test_touch_currency_picker_fits_phone_and_preserves_original_amount(window, app):
    item = offer(); window.mode = 'search'; window.offers = [item]; window.render_offers()
    original = item.to_dict(); window.currency.showPopup(); app.processEvents()
    assert window.currency.popup.width() <= window.width()
    window.currency.search.setText('usd'); app.processEvents()
    assert window.currency.items.count() == 1
    row = window.currency.items.item(0)
    assert row.sizeHint().height() >= 44
    window.currency.choose(row)
    assert window.currency.currentData() == 'USD' and item.to_dict() == original
    assert Store(window.data_dir).data['settings']['display_currency'] == 'USD'


def test_native_file_export_keeps_decimal_source_links_and_formula_escaping(window, app, tmp_path, monkeypatch):
    item = offer(); item.model = '=formula'
    window.mode = 'search'; window.offers = [item]; window.render_offers()
    destination = tmp_path / 'offers.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (str(destination), 'CSV (*.csv)'))
    window.export_csv()
    with destination.open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.reader(handle, delimiter=';'))
    assert len(rows) == 2 and len(rows[1]) == 13
    assert rows[1][2] == "'=formula" and rows[1][6] == '1.23456789'
    assert rows[1][7] == 'GRAM' and rows[1][-1] == item.link


def test_android_content_uri_is_passed_to_qt_without_filesystem_conversion(window, monkeypatch):
    import giftfinder.mobile_ui as mobile
    window.mode = 'search'; window.offers = [offer()]; window.render_offers()
    document = 'content://com.android.providers.downloads.documents/document/test-export'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args, **kwargs: (document, 'CSV (*.csv)'))
    saved = {}
    class AndroidDocument:
        def __init__(self, name): saved['uri'] = name
        def open(self, flags): saved['mode'] = flags; return True
        def write(self, payload): saved['payload'] = payload; return len(payload)
        def close(self): saved['closed'] = True
        def errorString(self): return ''
    monkeypatch.setattr(mobile, 'QFile', AndroidDocument)
    window.export_csv()
    assert saved['uri'] == document and saved['closed']
    assert saved['payload'].startswith(b'\xef\xbb\xbf')
    assert 'Easter Egg;42' in saved['payload'].decode('utf-8-sig')


def test_synthetic_csv_requires_smoke_mode_and_does_not_open_picker_in_normal_mode(window, monkeypatch):
    monkeypatch.delenv('GIFT_FINDER_ANDROID_SMOKE', raising=False)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: pytest.fail('Normal mode must not start a synthetic export'))
    with pytest.raises(RuntimeError, match='explicit Android smoke mode'):
        window.smoke_export_csv()
    assert not window.offer_model.offers


def test_smoke_csv_uses_native_export_readback_and_restores_offers_without_profile_writes(window, tmp_path, monkeypatch, capsys):
    from PySide6.QtCore import QFile as RealFile
    import giftfinder.mobile_ui as mobile
    monkeypatch.setenv('GIFT_FINDER_ANDROID_SMOKE', '1')
    uri = 'content://com.android.providers.downloads.documents/document/ci-export'
    destination = tmp_path / 'ci-native-export.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (uri, 'CSV (*.csv)'))
    def native_file(path):
        assert path == uri
        return RealFile(str(destination))
    monkeypatch.setattr(mobile, 'QFile', native_file)
    previous = [offer()]; window.offer_model.replace(previous)
    profile = {path.relative_to(window.data_dir): path.read_bytes() for path in window.data_dir.rglob('*') if path.is_file()}
    window.smoke_export_csv()
    assert capsys.readouterr().out.count('GIFTFINDER_ANDROID_CSV_SAVED') == 1
    assert window.offer_model.offers == previous and not window.offers
    assert {path.relative_to(window.data_dir): path.read_bytes() for path in window.data_dir.rglob('*') if path.is_file()} == profile
    assert 'CI synthetic offer' in destination.read_text(encoding='utf-8-sig')


def test_smoke_csv_rejects_bad_native_readback_without_success_marker(window, monkeypatch, capsys):
    import giftfinder.mobile_ui as mobile
    monkeypatch.setenv('GIFT_FINDER_ANDROID_SMOKE', '1')
    monkeypatch.setattr(window, 'export_csv', lambda: 'content://documents/ci-export')
    class WrongDocument:
        def __init__(self, path): pass
        def open(self, flags): return True
        def readAll(self): return b'wrong;data\n'
        def close(self): pass
    monkeypatch.setattr(mobile, 'QFile', WrongDocument)
    with pytest.raises(RuntimeError, match='did not match the synthetic fixture'):
        window.smoke_export_csv()
    assert 'GIFTFINDER_ANDROID_CSV_SAVED' not in capsys.readouterr().out
    assert not window.offer_model.offers


def test_filter_price_currency_picker_reuses_full_currency_catalog(window, app):
    window.open_filters(); dialog = window.filter_dialog
    assert dialog.unit.count() >= 160
    dialog.advanced_toggle.click(); app.processEvents()
    dialog.unit.showPopup(); dialog.unit.search.setText('usd'); app.processEvents()
    assert dialog.unit.popup.width() <= window.width()
    assert dialog.unit.items.count() == 1
    dialog.unit.choose(dialog.unit.items.item(0))
    assert dialog.unit.currentData() == 'USD'


def test_saved_search_list_and_source_dialog_fit_phone(window, app):
    window.filter_query = SearchQuery(collection='Input Key', models=('Creeper',))
    window.filter_extra = {'min':'2','max':'50','unit':'USD'}
    window.save_search(); assert Store(window.data_dir).data['searches']
    expected = window.filter_query; calls = []
    window.start_search = lambda: calls.append(window.current_query())
    window.filter_query = SearchQuery(); window.filter_extra = {}
    window.saved_searches(); settle(window)
    dialog = window.dialogs[-1]
    assert dialog.width() == 360
    dialog.findChild(QListWidget).setCurrentRow(0)
    next(child for child in dialog.findChildren(MotionButton) if child.text() == tr('open_search')).click()
    app.processEvents()
    assert calls == [expected]
    assert window.filter_extra == {'min':'2','max':'50','unit':'USD'}
    window.sources_info(); settle(window)
    assert window.dialogs[-1].width() == 360
    window.handle_back(); app.processEvents()
    assert window.isVisible()


@pytest.mark.parametrize('key', [Qt.Key.Key_Back, Qt.Key.Key_Escape])
def test_back_closes_menu_before_main_window(window, app, key):
    menu = QMenu(window)
    menu.addAction('Rates')
    menu.popup(window.mobile_menu_button.mapToGlobal(QPoint(0, 0)))
    app.processEvents()
    assert app.activePopupWidget() is menu
    QTest.keyClick(menu, key); app.processEvents()
    assert not menu.isVisible()
    assert window.isVisible() and window.mode == 'catalog'
    menu.deleteLater()


def test_back_closes_category_popup_before_cancelling_filter_draft(window, app):
    original = SearchQuery(collection='Input Key', models=('Creeper',))
    window.filter_query = original
    window.open_filters(); dialog = window.filter_dialog
    dialog.number.setText('42')
    draft = dialog.state
    dialog.category_select.showPopup(); app.processEvents()
    popup = app.activePopupWidget()
    assert popup is not None
    QTest.keyClick(popup, Qt.Key.Key_Back); app.processEvents()
    assert not popup.isVisible() and window.filter_dialog is dialog
    assert dialog.number.text() == '42' and dialog.state == draft
    assert window.filter_query == original
    QTest.keyClick(dialog.search, Qt.Key.Key_Back); app.processEvents()
    assert window.filter_dialog is None and window.filter_query == original


def swipe_up(view, device):
    viewport = view.viewport()
    x = viewport.width() // 2
    start = min(viewport.height()-20, 400)
    sequence = QTest.touchEvent(viewport, device)
    sequence.press(0, QPoint(x, start), viewport).commit()
    for step in range(1, 11):
        QTest.qWait(15)
        sequence.move(0, QPoint(x, start-step*22), viewport).commit()
    sequence.release(0, QPoint(x, start-220), viewport).commit()
    QTest.qWait(60)


def test_language_list_scrolls_by_touch_without_selecting_a_language(window, app, touch_device):
    window.language_menu(); app.processEvents()
    dialog = window.dialogs[-1]
    languages = dialog.findChild(QListWidget)
    assert languages.accessibleIdentifier() == 'mobileLanguageList'
    before = window.store.data['settings']['language']
    assert languages.verticalScrollBar().maximum() > 0
    swipe_up(languages, touch_device)
    assert languages.verticalScrollBar().value() > 0
    assert dialog.isVisible() and window.store.data['settings']['language'] == before


def test_language_list_still_accepts_an_ordinary_touch_tap(window, app, touch_device):
    window.language_menu(); app.processEvents()
    dialog = window.dialogs[-1]
    languages = dialog.findChild(QListWidget)
    row = next(i for i in range(languages.count()) if languages.item(i).data(Qt.ItemDataRole.UserRole) == 'ru')
    point = languages.visualItemRect(languages.item(row)).center()
    sequence = QTest.touchEvent(languages.viewport(), touch_device)
    sequence.press(0, point, languages.viewport()).commit()
    QTest.qWait(30)
    sequence.release(0, point, languages.viewport()).commit()
    app.processEvents()
    assert window.store.data['settings']['language'] == 'ru'
    assert dialog not in window.dialogs


def test_saved_search_list_scrolls_by_touch_without_loading_a_query(window, app, touch_device):
    for number in range(1, 31):
        window.filter_query = SearchQuery(collection='Easter Egg', number=number)
        window.save_search()
    original = window.filter_query
    window.saved_searches(); app.processEvents()
    dialog = window.dialogs[-1]
    searches = dialog.findChild(QListWidget)
    assert searches.verticalScrollBar().maximum() > 0
    swipe_up(searches, touch_device)
    assert searches.verticalScrollBar().value() > 0
    assert dialog.isVisible() and window.filter_query == original
