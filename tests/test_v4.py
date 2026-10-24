import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import replace
from decimal import Decimal
from string import Formatter
import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QSize,QPoint,QLocale
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from giftfinder.ui import MainWindow
from giftfinder.ui_common import application
from giftfinder.core import SearchQuery,Store,Offer
from giftfinder.i18n import EN,LANGUAGES,translations,resolve_language,set_language,language_code,currency_name,tr,format_number
from giftfinder.icons import flag_icon,currency_icon,COUNTRIES

@pytest.fixture(scope='module')
def app():return QApplication.instance() or application()

@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR',str(tmp_path));w=MainWindow(offline=True);w.show();app.processEvents()
    yield w
    w.close();app.processEvents();set_language('ru')

def test_collection_cancel_keeps_active_search_text_budget_and_saved_state(window,app):
    w=window;q=SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',))
    w.filter_query=q;w.filter_extra={'min':'1,5','max':'25','unit':'GRAM'};w.search_edit.setText('original text')
    w.filter_summary();w.store.data['settings']['last_filter']={'collection':'Easter Egg'};w.store.save()
    extra=dict(w.filter_extra);saved=dict(w.store.data['settings']['last_filter'])
    index=next(w.home_model.index(i) for i,r in enumerate(w.home_model.rows) if r['name']=='Artisan Brick')
    w.choose_collection(index);app.processEvents();d=w.filter_dialog
    assert d.state.collection=='Artisan Brick' and w.filter_query==q and w.filter_extra==extra
    assert w.search_edit.text()=='original text'
    d.choose(d.rows.index(0));d.change_tab('backdrops');d.choose(d.rows.index(0));d.reject();app.processEvents()
    assert w.filter_dialog is None and w.filter_query==q and w.filter_extra==extra
    assert w.search_edit.text()=='original text' and w.store.data['settings']['last_filter']==saved

def test_collection_apply_commits_once_and_clears_old_text_only_on_apply(window,app):
    w=window;w.search_edit.setText('unrelated');calls=[]
    original=w.start_search
    w.start_search=lambda:(calls.append(w.current_query()),original())
    i=next(i for i,r in enumerate(w.home_model.rows) if r['name']=='Easter Egg');w.choose_collection(w.home_model.index(i))
    d=w.filter_dialog;index=next(i for i,r in enumerate(d.rows.rows) if r['name']=='Creeper');d.choose(d.rows.index(index))
    assert not calls and not w.filter_query.collection
    d.apply();app.processEvents()
    assert len(calls)==1 and w.filter_query.collection=='Easter Egg' and w.search_edit.text()==''
    assert w.filter_query.targets==( ('Easter Egg','Creeper'), )
    assert w.active_widget.isVisible()

def test_collection_draft_preserves_existing_price_range_and_unit(window):
    w=window;w.filter_extra={'min':'10','max':'20','unit':'USD'}
    row=next(i for i,r in enumerate(w.home_model.rows) if r['name']=='Easter Egg')
    w.choose_collection(w.home_model.index(row));d=w.filter_dialog
    assert d.minimum.text()=='10' and d.maximum.text()=='20' and d.unit.currentData()=='USD'
    d.apply();assert w.filter_extra=={'min':'10','max':'20','unit':'USD'}

def test_draft_price_currency_and_model_survive_language_change(window,app):
    w=window;w.open_filters('models',SearchQuery(collection='Easter Egg'))
    d=w.filter_dialog;d.minimum.setText('1,5');d.maximum.setText('2,5');d.unit.setCurrentIndex(d.unit.findData('USD'))
    d.state=replace(d.state,targets=(('Easter Egg','Creeper'),),backdrops=('Black',))
    old=w.filter_query;w.change_language('de');app.processEvents()
    assert w.filter_query==old and d.state.targets==( ('Easter Egg','Creeper'), )
    assert d.minimum.text()=='1,5' and d.maximum.text()=='2,5' and d.unit.currentData()=='USD'
    assert d.tabs['models'].text()==tr('model') and d.state.backdrops==('Black',)

def test_theme_collapse_and_language_persist_without_touching_other_settings(window,app):
    w=window;w.store.data['settings']['custom_preference']={'keep':True};w.store.save()
    original=w.themes_collapsed;w.toggle_themes();w.change_language('fr');data=Store(w.data_dir).data
    assert data['settings']['themes_collapsed']==(not original) and data['settings']['language']=='fr'
    assert data['settings']['custom_preference']=={'keep':True}
    w2=MainWindow(offline=True)
    assert w2.themes_collapsed==(not original) and language_code()=='fr'
    assert w2.find_button.text()=='Rechercher';w2.close()

def test_native_resizable_filter_frame(window,app):
    window.open_filters('themes');d=window.filter_dialog;app.processEvents()
    assert not d.windowFlags()&Qt.WindowType.FramelessWindowHint
    assert d.windowFlags()&Qt.WindowType.WindowMaximizeButtonHint
    d.resize(1220,850);assert d.size()==QSize(1220,850)
    d.close();app.processEvents();assert window.store.data['settings']['filter_geometry'][2:]==[1220,850]

def test_currency_button_opens_from_center_filters_and_esc_keeps_value(window,app):
    w=window;w.tools_widget.show();app.processEvents();c=w.currency;before=c.currentData()
    QTest.mouseClick(c,Qt.MouseButton.LeftButton,pos=c.rect().center());app.processEvents()
    assert c.popup.isVisible()
    QTest.keyClicks(c.search,'usd');app.processEvents();assert c.items.count()==1
    assert c.itemData(c.items.item(0).data(Qt.ItemDataRole.UserRole))=='USD'
    QTest.keyClick(c.search,Qt.Key.Key_Escape);app.processEvents()
    assert not c.popup.isVisible() and c.currentData()==before
    c.showPopup();c.search.setText('рубль');app.processEvents()
    assert {c.itemData(c.items.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(c.items.count())}=={'RUB','BYN'}
    c.search.setText('usd');QTest.keyClick(c.search,Qt.Key.Key_Return);app.processEvents()
    assert c.currentData()=='USD' and not c.popup.isVisible()
    assert Store(w.data_dir).data['settings']['display_currency']=='USD'
    assert w.assets.network_started==0

def test_currency_and_language_changes_do_not_change_original_prices_or_run_search(window,app):
    w=window;offers=[Offer('EasterEgg-1','Easter Egg',1,'fragment',Decimal('1.23456789'),'TON','Creeper','Black'),Offer('EasterEgg-2','Easter Egg',2,'telegram',Decimal('50'),'Stars','Creeper','Black')]
    w.mode='search';w.offers=offers;w.render_offers();original=[o.to_dict() for o in offers]
    w.engine.search=lambda *args:pytest.fail('Display setting triggered network search')
    for locale in ('en','de','ar','ja','ru'):
        w.change_language(locale)
        for currency in ('USD','EUR','RUB','Stars','GRAM','ORIGINAL'):
            w.currency.setCurrentIndex(w.currency.findData(currency));app.processEvents()
            assert w.offer_model.rowCount()==2 and [o.to_dict() for o in offers]==original
    assert w.assets.network_started==0

@pytest.mark.parametrize('system,expected',[('ru_RU','ru'),('en_US','en'),('pt_BR','pt_BR'),('pt_AO','pt_PT'),('zh_Hant_HK','zh_TW'),('zh_Hans_CN','zh_CN'),('xx_XX','en')])
def test_system_language_resolution(system,expected):assert resolve_language('system',system)==expected

def test_system_uses_windows_ui_language_instead_of_regional_number_format(monkeypatch):
    import giftfinder.i18n as i18n
    class System:
        def uiLanguages(self):return ['fr-Latn-CA','en-US']
        def name(self):return 'de_DE'
    class Locale:
        @staticmethod
        def system():return System()
    monkeypatch.setattr(i18n,'QLocale',Locale)
    assert i18n.resolve_language('system')=='fr'

def test_language_defaults_to_system_and_manual_choice_is_separate(window):
    assert 'language' not in window.store.data['settings']
    assert language_code()==resolve_language('system')
    window.change_language('ja');assert language_code()=='ja'
    window.change_language('system');assert language_code()==resolve_language('system')
    assert window.store.data['settings']['language']=='system'

def test_all_language_packs_have_every_message_and_valid_placeholders(app):
    placeholders=lambda s:{name for _,name,_,_ in Formatter().parse(s) if name}
    for code in LANGUAGES:
        pack=translations(code) if code!='en' else EN
        assert set(pack)==set(EN),(code,set(EN)-set(pack))
        for key,value in pack.items():assert value and placeholders(value)==placeholders(EN[key]),(code,key)
        assert all(currency_name(c,code) for c in ('RUB','USD','EUR','KZT','JPY','AED'))

def test_flags_currency_symbols_and_rtl_are_native_rendered(app):
    for code in ['system']+list(LANGUAGES):assert not flag_icon(code).pixmap(36,28).isNull()
    from giftfinder.icons import symbols
    for code in list(symbols())+['GRAM','Stars','ORIGINAL']:assert not currency_icon(code).pixmap(32,32).isNull()
    set_language('ar');assert app.layoutDirection()==Qt.LayoutDirection.RightToLeft
    set_language('ru');assert app.layoutDirection()==Qt.LayoutDirection.LeftToRight
    assert format_number(Decimal('1234.50'))=='1\u00a0234,5'

def test_rates_dialog_keeps_numeric_rates_dates_and_currency_live(window):
    from PySide6.QtWidgets import QLabel
    w=window;w.rates_info();d=w.dialogs[-1]
    body=d.layout().itemAt(1).widget()
    assert '1 GRAM ≈' in body.text() and '1 Star ≈' in body.text() and 'ExchangeRate-API' in body.text()
    w.currency.setCurrentIndex(w.currency.findData('USD'))
    assert '$' in body.text()
    w.currency.setCurrentIndex(w.currency.findData('ORIGINAL'))
    assert '1 GRAM ≈' in body.text()

def test_many_applied_filters_wrap_and_keep_reset_reachable(window,app):
    w=window;w.mode='search'
    w.filter_query=SearchQuery(collection='Easter Egg',theme='minecraft',models=('Creeper','Baby Turtle','Baby Chick'),
        backdrops=('Black','Aquamarine','Burgundy'),symbols=('Cherry','Snowflake','Twin Koi'),number=123456)
    w.filter_extra={'min':'100','max':'20000','unit':'USD'};w.filter_summary();w.resize(1050,740);app.processEvents()
    assert w.minimumSizeHint().width()<=1050 and w.active_widget.height()>40
    for i in range(w.active_row.count()):
        rect=w.active_row.itemAt(i).widget().geometry()
        assert rect.left()>=0 and rect.right()<=w.active_widget.width() and rect.bottom()<=w.active_widget.height()

def test_tooltips_follow_selected_language(window):
    w=window;w.change_language('en');w.currency.setCurrentIndex(w.currency.findData('RUB'))
    assert 'Russian' in w.currency.toolTip()
    w.offer_model.replace([Offer('EasterEgg-1','Easter Egg',1,'fragment',Decimal('1'),'TON')])
    assert 'Time unknown' in w.offer_model.index(0).data(Qt.ItemDataRole.ToolTipRole)
