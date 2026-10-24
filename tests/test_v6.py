import os,json
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import asdict,replace
from decimal import Decimal
import pytest
from PySide6.QtCore import Qt,QRect,QSize
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QStyleOptionViewItem
from giftfinder.ui import MainWindow
from giftfinder.ui_common import application
from giftfinder.catalogue import Catalog,query_from_dict
from giftfinder.core import SearchQuery,Offer,Store
from giftfinder.cache import ListingCache
from giftfinder import monochrome
from giftfinder.i18n import LANGUAGES,set_language,tr
from giftfinder.qa import settle

@pytest.fixture(scope='module')
def app():return QApplication.instance() or application()

@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR',str(tmp_path));w=MainWindow(offline=True);w.show();app.processEvents()
    yield w
    w.close();app.processEvents();set_language('ru')

def offer(c,m,b,n=1):return Offer(c.replace(' ','')+'-'+str(n),c,n,'fragment',Decimal('1.23456789'),'TON',m,b)

def choose_color(dialog,color):
    i=next(i for i,r in enumerate(dialog.rows.rows) if r['key']==color)
    dialog.choose(dialog.rows.index(i))

def test_home_monochromes_click_opens_colors_first_without_applying(window,app):
    w=window;w.filter_query=SearchQuery(collection='Easter Egg',models=('Creeper',));w.filter_extra={'min':'1','max':'20','unit':'USD'}
    w.search_edit.setText('keep this text');old=w.filter_query;generation=w.generation;saved=dict(w.store.data['settings'])
    i=next(i for i,r in enumerate(w.theme_model.rows) if r['key']=='monochrome')
    rect=w.theme_grid.visualRect(w.theme_model.index(i));QTest.mouseClick(w.theme_grid.viewport(),Qt.MouseButton.LeftButton,pos=rect.center());app.processEvents()
    d=w.filter_dialog;assert d and d.category=='colors' and d.rows.rowCount()==14
    assert d.state.monochrome and not d.state.collection and not d.state.models and not d.state.targets
    assert w.filter_query==old and w.search_edit.text()=='keep this text' and w.generation==generation
    choose_color(d,'black');assert d.state.mono_colors==('black',) and w.filter_query==old
    d.reject();app.processEvents()
    assert w.filter_query==old and w.filter_extra=={'min':'1','max':'20','unit':'USD'}
    assert w.store.data['settings'].get('last_filter')==saved.get('last_filter')

def test_color_apply_searches_every_collection_and_remembers_selection(window,app):
    w=window;w.search_theme('monochrome');d=w.filter_dialog;choose_color(d,'black');d.apply();app.processEvents()
    assert w.filter_query.monochrome and w.filter_query.mono_colors==('black',) and not w.filter_query.collection
    variants,_=w.catalog.resolve(w.filter_query)
    assert len(variants)>10 and all(v.mono_colors==('black',) for v in variants)
    assert sum(len(v.models) for v in variants)==100
    assert Store(w.data_dir).data['settings']['last_filter']['mono_colors']==['black']
    w.open_filters();assert w.filter_dialog.state.mono_colors==('black',)

@pytest.mark.parametrize('color',list(monochrome.COLORS))
def test_each_color_covers_all_approved_models_across_collections(tmp_path,color):
    c=Catalog(tmp_path);q=SearchQuery(mono_colors=(color,))
    variants,_=c.resolve(q)
    actual={(v.collection,m) for v in variants for m in v.models}
    expected={(r['collection'],r['model']) for r in monochrome.data()['models'] if r['family']==color}
    assert actual==expected and len({c for c,m in actual})>1
    for v in variants:
        assert v.monochrome
        for model in v.models:
            bg=monochrome.backgrounds(v.collection,model)[0]
            assert v.matches(offer(v.collection,model,bg))

def test_color_filter_uses_model_family_and_still_checks_exact_backdrop():
    green=SearchQuery(monochrome=True,mono_colors=('green',))
    assert green.matches(offer('Input Key','Creeper','Malachite'))
    assert not green.matches(offer('Input Key','Creeper','Sapphire'))
    assert not green.matches(offer('Perfume Bottle','Noir','Black'))
    both=replace(green,mono_colors=('green','black'))
    assert both.matches(offer('Perfume Bottle','Noir','Black'))
    assert not both.matches(offer('Perfume Bottle','Noir','Rifle Green'))

def test_collection_theme_background_and_color_intersect(tmp_path):
    c=Catalog(tmp_path);q=SearchQuery(collection='Input Key',theme='minecraft',mono_colors=('green',),backdrops=('Malachite',))
    variants,_=c.resolve(q);assert len(variants)==1 and variants[0].models==('Creeper',)
    with pytest.raises(ValueError):c.resolve(replace(q,mono_colors=('black',)))
    with pytest.raises(ValueError):c.resolve(replace(q,mono_colors=('not-a-color',)))

def test_cache_color_filter_and_invalidation_do_not_touch_other_colors(tmp_path):
    cache=ListingCache(tmp_path);c=Catalog(tmp_path)
    black=offer('Input Key','Coffee','Black');green=offer('Input Key','Creeper','Malachite',2)
    assert monochrome.family(black.collection,black.model)=='black'
    cache.save([black,green]);queries,_=c.resolve(SearchQuery(collection='Input Key',mono_colors=('black',)))
    assert [o.model for o in cache.find(queries).offers]==['Coffee']
    cache.remove_absent(queries[0],'fragment',set())
    assert [o.model for o in cache.find([SearchQuery(collection='Input Key')]).offers]==['Creeper']

def test_multiple_colors_all_colors_and_old_profile_round_trip(window):
    w=window;w.search_theme('monochrome');d=w.filter_dialog
    choose_color(d,'black');choose_color(d,'green');assert d.state.mono_colors==('black','green')
    choose_color(d,'black');assert d.state.mono_colors==('green',)
    choose_color(d,'');assert not d.state.mono_colors and d.state.monochrome
    assert query_from_dict({'monochrome':True}).mono_colors==()
    q=SearchQuery(monochrome=True,mono_colors=('black','green'))
    assert query_from_dict(json.loads(json.dumps(asdict(q))))==q

def test_theme_enables_color_screen_and_removing_monochrome_clears_colors(window):
    w=window;w.open_filters('themes');d=w.filter_dialog
    i=next(i for i,r in enumerate(d.rows.rows) if r['key']=='monochrome');d.choose(d.rows.index(i))
    assert d.category=='colors' and d.tabs['colors'].isVisible()
    choose_color(d,'green');d.apply();assert w.filter_query.mono_colors==('green',)
    w.remove_filter('mono_colors');assert w.filter_query.monochrome and not w.filter_query.mono_colors
    w.remove_filter('monochrome');assert not w.filter_query.monochrome and not w.filter_query.mono_colors

def test_color_selection_and_counts_survive_all_language_changes(window,app):
    w=window;w.search_theme('monochrome');d=w.filter_dialog;choose_color(d,'green');count=d.rows.rowCount()
    for code in LANGUAGES:
        w.change_language(code);app.processEvents()
        assert d.category=='colors' and d.state.mono_colors==('green',) and d.rows.rowCount()==count==14
        assert next(r['name'] for r in d.rows.rows if r['key']=='green')==tr('color_green')
        assert all(not r['name'].startswith('color_') for r in d.rows.rows)

def test_ribbon_hover_animates_inside_card_and_restores_identical_pixels(window,app):
    w=window;settle(w);view=w.theme_grid;delegate=view.itemDelegate();index=w.theme_model.index(0)
    option=QStyleOptionViewItem();option.rect=QRect(25,25,220,100)
    def render(amount):
        view.hovered_row=0;view.previous_row=-1;view.set_hover(amount)
        image=QImage(280,160,QImage.Format.Format_ARGB32);image.fill(QColor('#ff00aa'))
        painter=QPainter(image);delegate.paint(painter,option,index);painter.end();return image
    first=render(0);middle=render(.4);last=render(1);restored=render(0)
    assert first!=middle and middle!=last and first==restored
    for image in (first,middle,last):
        for x,y in ((24,50),(245,80),(50,24),(50,125),(80,150)):assert image.pixelColor(x,y)==QColor('#ff00aa')

def test_theme_hover_reuses_collection_timing_and_reduced_motion(window,app,monkeypatch):
    from giftfinder import views
    view=window.theme_grid;assert view.hover_animation.duration()==window.home_grid.hover_animation.duration()==140
    monkeypatch.setattr(views,'motion_enabled',lambda:True)
    view.reset_hover();view.set_hover_row(0);QTest.qWait(60)
    assert 0<view.hover_amount<1
    QTest.qWait(130);assert view.hover_animation.state()==view.hover_animation.State.Stopped
    monkeypatch.setattr(views,'motion_enabled',lambda:False)
    view.set_hover_row(-1);assert view.hover_amount==1 and view.hover_animation.state()==view.hover_animation.State.Stopped
