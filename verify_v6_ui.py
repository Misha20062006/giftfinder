"""Color-first flow and animation snapshots with isolated, offscreen UI."""
import os,sys,json
from pathlib import Path
from dataclasses import replace
target=Path(sys.argv[1]).resolve();target.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['GIFT_FINDER_DATA_DIR']=str(target/'profile')
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from giftfinder.ui import MainWindow,application
from giftfinder.core import SearchQuery,Offer
from giftfinder.i18n import LANGUAGES
from giftfinder.monochrome import COLORS
from giftfinder.qa import settle
app=application();w=MainWindow(offline=True);w.show();w.change_language('ru');settle(w)
def save(name,widget=None):
    app.processEvents();settle(w);(widget or w).grab().save(str(target/(name+'.png')))
save('catalog')
w.search_theme('monochrome');d=w.filter_dialog;app.processEvents();assert d.category=='colors' and d.rows.rowCount()==14
save('color-first',d)
def choose(color):
    i=next(i for i,r in enumerate(d.rows.rows) if r['key']==color);d.choose(d.rows.index(i))
choose('green');save('color-green',d);choose('black');save('color-multiple',d)
before=w.filter_query;translations={}
for code in LANGUAGES:
    w.change_language(code);app.processEvents()
    assert d.state.mono_colors==('green','black') and w.filter_query==before
    save('colors-'+code,d);translations[code]=[r['name'] for r in d.rows.rows]
w.change_language('ru');d.apply();app.processEvents()
assert w.filter_query.mono_colors==('green','black') and not w.filter_query.collection
variants,_=w.catalog.resolve(w.filter_query)
assert len(variants)>10
offers_path=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else None
if offers_path:
    offers=[Offer.from_dict(r) for r in json.loads(offers_path.read_text(encoding='utf8'))]
    w.offers=[o for o in offers if w.filter_query.matches(o)];assert w.offers
    w.render_offers();save('color-results')
w.save_search();assert w.store.data['searches'][-1]['mono_colors']==['green','black']
w.show_catalog();settle(w)
row=next(i for i,r in enumerate(w.theme_model.rows) if r['key']=='monochrome')
w.theme_grid.hovered_row=row;w.theme_grid.previous_row=-1
for value,name in [(0,'theme-idle'),(.4,'theme-hover-middle'),(1,'theme-hover')]:
    w.theme_grid.set_hover(value);save(name)
w.theme_grid.set_hover(0);save('theme-restored')
w.resize(1050,740);save('compact')
w.search_theme('monochrome');d=w.filter_dialog;d.resize(760,560);save('color-compact',d);d.reject()
report={'result':'PASS','colors':len(COLORS),'languages':len(translations),'saved_colors':w.filter_query.mono_colors,
    'resolved_collections':len(variants),'normal_profile_used':False,'network_requests':w.assets.network_started,
    'desktop_interaction':False,'real_search_performed':False}
(target/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
w.close();print(json.dumps(report))
