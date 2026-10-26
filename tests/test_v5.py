import os,json,threading
os.environ['QT_QPA_PLATFORM']='offscreen'
from dataclasses import asdict,replace
from decimal import Decimal
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QSize,QRect
from PySide6.QtGui import QImage,QPainter,QColor
from PySide6.QtWidgets import QApplication,QStyleOptionViewItem
from giftfinder.ui import MainWindow
from giftfinder.ui_common import application
from giftfinder.core import SearchQuery,Offer,SearchResult,SourceStatus
from giftfinder.catalogue import Catalog,query_from_dict
from giftfinder import monochrome,providers
from giftfinder.design import MotionButton
from giftfinder.i18n import LANGUAGES,set_language,tr

@pytest.fixture(scope='module')
def app():return QApplication.instance() or application()

@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR',str(tmp_path));w=MainWindow(offline=True);w.show();app.processEvents()
    yield w
    w.close();app.processEvents();set_language('ru')

def offer(c,m,b):return Offer('InputKey-1',c,1,'fragment',Decimal('1.23456789'),'TON',m,b)

def test_monochrome_exact_triples_never_join_other_models_backdrops():
    q=SearchQuery(monochrome=True)
    assert q.matches(offer('Input Key','Creeper','Malachite'))
    assert q.matches(offer('Input Key','Telegram','Sapphire'))
    assert not q.matches(offer('Input Key','Creeper','Sapphire'))
    assert not q.matches(offer('Input Key','Telegram','Malachite'))
    assert not q.matches(offer('Perfume Bottle','Noir','Rifle Green'))
    assert q.matches(offer('Perfume Bottle','Noir','Black'))
    assert not q.matches(offer('Missing','Unknown','Black'))

def test_monochrome_full_catalog_coverage_and_placeholder_exclusions(tmp_path):
    c=Catalog(tmp_path);data=monochrome.data();known={(r['collection'],r['name']) for r in c.model_rows}
    assert data['coverage']['models_analyzed']==len(known)==7806
    assert data['coverage']['backdrops_analyzed']==len(c.backdrop_lookup)==80
    assert data['coverage']['pairs']==sum(len(r['backdrops']) for r in data['models'])
    assert all((r['collection'],r['model']) in known and r['backdrops'] for r in data['models'])
    assert all(b.casefold() in c.backdrop_lookup for r in data['models'] for b in r['backdrops'])
    for pair in [('Eternal Candle','Ephemeral'),('Ginger Cookie','Cooking...'),('Plush Pepe','Toading...'),('Toy Bear','Zebra')]:
        assert not monochrome.has_model(*pair)

def test_monochrome_combines_collection_theme_model_and_background(tmp_path):
    c=Catalog(tmp_path)
    q=SearchQuery(collection='Input Key',theme='minecraft',monochrome=True,backdrops=('Malachite',))
    variants,_=c.resolve(q)
    assert len(variants)==1 and variants[0].models==('Creeper',) and variants[0].monochrome
    assert variants[0].matches(offer('Input Key','Creeper','Malachite'))
    assert not variants[0].matches(offer('Input Key','Creeper','Black'))
    with pytest.raises(ValueError):c.resolve(replace(q,backdrops=('Black',)))
    global_variants,_=c.resolve(SearchQuery(theme='monochrome'))
    assert len(global_variants)>100 and all(v.monochrome for v in global_variants)
    assert query_from_dict(json.loads(json.dumps(asdict(q))))==q

def test_all_themes_visible_expanded_at_normal_and_minimum_window_size(window,app):
    w=window
    assert w.theme_model.rowCount()==len(w.catalog.themes)==20
    assert any(r['key']=='monochrome' for r in w.theme_model.rows)
    for size in [(1400,900),(1050,740)]:
        w.resize(*size);app.processEvents();w.theme_grid.doItemsLayout();app.processEvents()
        viewport=w.theme_grid.viewport().rect()
        assert w.theme_grid.verticalScrollBar().maximum()>0
        assert w.theme_grid.horizontalScrollBar().maximum()==0
        assert w.home_grid.viewport().height()>=w.home_grid.gridSize().height()
        for i in range(w.theme_model.rowCount()):
            index=w.theme_model.index(i);w.theme_grid.scrollTo(index);app.processEvents()
            assert viewport.contains(w.theme_grid.visualRect(index))
    w.toggle_themes();assert not w.theme_grid.isVisible()
    w.toggle_themes();assert w.theme_grid.isVisible()

def test_button_natural_width_has_one_complete_line_in_all_languages(window,app):
    for code in LANGUAGES:
        window.change_language(code);app.processEvents()
        for b in window.findChildren(MotionButton):
            if not b.text():continue
            width=b.sizeHint().width()-b.text_space();layout,height=b.text_layout(width)
            assert layout.lineCount()==1,(code,b.text(),b.sizeHint(),width)
            assert layout.lineAt(0).textLength()==len(b.text()),(code,b.text())

def test_visible_buttons_keep_full_text_at_minimum_width_in_all_languages(window,app):
    w=window;w.resize(1050,740)
    for code in LANGUAGES:
        w.change_language(code);app.processEvents()
        for b in w.findChildren(MotionButton):
            if not b.isVisible() or not b.text():continue
            layout,height=b.text_layout(b.width()-b.text_space())
            assert height<=b.height()-4,(code,b.text(),b.width(),b.height(),height)

def test_long_filter_labels_wrap_fully_and_remain_inside_widget(window,app):
    w=window;w.mode='search';w.resize(1050,740)
    models=tuple(r['name'] for r in w.catalog.model_rows[:50])
    w.filter_query=SearchQuery(collection='B-Day Candle',models=models,monochrome=True)
    w.filter_summary();app.processEvents()
    for i in range(w.active_row.count()):
        b=w.active_row.itemAt(i).widget();layout,height=b.text_layout(b.width()-b.text_space())
        assert sum(layout.lineAt(j).textLength() for j in range(layout.lineCount()))==len(b.text())
        assert height<=b.height()-4,(b.text(),b.height(),height)
        assert b.geometry().right()<w.active_widget.width()
    assert any(w.active_row.itemAt(i).widget().height()>40 for i in range(w.active_row.count()))

def test_monochrome_filter_is_draft_and_backdrops_are_compatible(window,app):
    w=window;w.open_filters('themes',SearchQuery(collection='Input Key',targets=(('Input Key','Creeper'),)))
    d=w.filter_dialog;i=next(i for i,r in enumerate(d.rows.rows) if r['key']=='monochrome')
    d.choose(d.rows.index(i));assert d.state.monochrome and not w.filter_query.monochrome
    d.change_tab('backdrops');assert {r['name'] for r in d.rows.rows}==set(monochrome.backgrounds('Input Key','Creeper'))
    d.reject();app.processEvents();assert not w.filter_query.monochrome

def test_finished_progress_follows_language_change_without_new_search(window,app):
    w=window;w.mode='search';w.result.progress={'phase':'complete','checked':3,'total':3,'pages':4,'errors':0}
    w.update_progress(w.result.progress);generation=w.generation
    w.change_language('en');app.processEvents();assert 'Checks: 3/3' in w.progress_label.text()
    w.change_language('ru');app.processEvents();assert 'Проверки: 3/3' in w.progress_label.text()
    assert w.generation==generation and not w.busy

def test_stopping_before_first_source_response_stops_indeterminate_bar(window):
    w=window;w.change_language('en');w.mode='search';w.busy=True
    w.update_progress({'phase':'searching'})
    assert w.progress_bar.maximum()==0
    w.stop_search()
    assert not w.busy and w.progress_bar.maximum()==1
    assert 'Stopped' in w.progress_label.text() and 'Updating' not in w.progress_label.text()

def test_delegate_never_paints_outside_its_item_at_any_hover_frame(window,app):
    w=window;view=w.theme_grid;delegate=view.itemDelegate();index=w.theme_model.index(0)
    option=QStyleOptionViewItem();option.rect=QRect(25,25,220,100)
    for hover in (0,.25,.7,1):
        view.hovered_row=0;view.set_hover(hover);canvas=QImage(280,155,QImage.Format.Format_ARGB32);canvas.fill(QColor('#ef00ab'))
        p=QPainter(canvas);delegate.paint(p,option,index);p.end()
        for x,y in [(24,50),(245,80),(50,24),(50,125),(90,140)]:assert canvas.pixelColor(x,y)==QColor('#ef00ab')

def test_progress_waits_for_last_page_and_keeps_provider_call_sequence(monkeypatch):
    calls=[];snapshots=[];release=threading.Event()
    class C:
        def resolve(self,q):return [q],'scope'
    def native(q,known,offset='',**kwargs):
        calls.append(offset)
        if not offset:return SearchResult(statuses=[SourceStatus('fragment','ok',source='direct',has_more=True)],cursors=[{'offset':'next','provider':'fragment','query':asdict(q)}])
        release.set();return SearchResult(statuses=[SourceStatus('fragment','ok',source='direct')])
    def index(*args,**kwargs):assert release.wait(3);return SearchResult()
    monkeypatch.setattr(providers,'fragment_search',native);monkeypatch.setattr(providers,'index_search',index)
    result=providers.SearchEngine(C()).search(SearchQuery(collection='Input Key',markets=('fragment',)),on_update=lambda r:snapshots.append(r))
    assert calls==['','next']
    assert snapshots[0].progress['checked']==0
    assert any(any(s.has_more for s in r.statuses) for r in snapshots)
    assert all(r.progress['checked']<r.progress['total'] for r in snapshots if any(s.has_more for s in r.statuses))
    assert result.progress=={'phase':'complete','checked':2,'total':2,'pages':3,'errors':0}

def test_failed_progress_reports_error_without_changing_cache_or_retrying(monkeypatch):
    calls=[]
    class C:
        def resolve(self,q):return [q],'scope'
    def index(*args,**kwargs):calls.append('index');raise TimeoutError()
    monkeypatch.setattr(providers,'index_search',index)
    result=providers.SearchEngine(C()).search(SearchQuery(collection='Input Key',markets=('telegram',)))
    assert calls==['index'] and result.progress['errors']==1
    assert result.statuses[0].state=='unavailable'

def test_cancelled_progress_never_claims_completion(monkeypatch):
    class C:
        def resolve(self,q):return [q],'scope'
    stop=threading.Event();stop.set()
    monkeypatch.setattr(providers,'index_search',lambda *a,**k:SearchResult())
    result=providers.SearchEngine(C()).search(SearchQuery(collection='Input Key',markets=('telegram',)),cancelled=stop)
    assert result.progress['phase']=='stopped' and result.progress['checked']<result.progress['total']
