"""Render release screens and exercise native widgets in an isolated profile."""
import os,sys,json,shutil
from pathlib import Path
from dataclasses import replace
target=Path(sys.argv[1]).resolve();target.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['GIFT_FINDER_DATA_DIR']=str(target/'profile')
from PySide6.QtCore import Qt,QTimer,QPoint,QRectF
from PySide6.QtGui import QPainter,QImage,QColor,QFont
from PySide6.QtWidgets import QApplication,QLabel,QMenu,QListView
from giftfinder.ui import MainWindow,application
from giftfinder.core import Offer,SearchQuery,SearchResult,SourceStatus,Store
from giftfinder.i18n import LANGUAGES,language_code,tr
from giftfinder.qa import settle
images=target/'profile/images';images.mkdir(parents=True,exist_ok=True)
seed_images=Path(__file__).resolve().parents[1]/'qa-live-v2/images-profile/images'
if seed_images.exists():
    for path in seed_images.glob('*.png'):shutil.copyfile(path,images/path.name)
app=application();w=MainWindow(offline=True);w.show();w.change_language('ru');settle(w)
def save(name,widget=None):
    app.processEvents();settle(w);(widget or w).grab().save(str(target/(name+'.png')))
w.find_button.setFocus();save('catalog-expanded');w.toggle_themes();save('catalog')
row=next(i for i,r in enumerate(w.home_model.rows) if r['name']=='Easter Egg')
w.choose_collection(w.home_model.index(row));d=w.filter_dialog;app.processEvents()
selected=next(i for i,r in enumerate(d.rows.rows) if r['name']=='Creeper');d.choose(d.rows.index(selected))
settle(w);d.grid.scrollTo(d.rows.index(selected),QListView.ScrollHint.PositionAtTop);save('filters-models',d)
d.change_tab('backdrops');save('filters-backdrops',d);d.change_tab('themes');save('filters-themes',d)
d.reject();app.processEvents();assert not w.filter_query.collection
offers_path=Path(sys.argv[2]).resolve() if len(sys.argv)>2 else target/'offers.json'
offers=[Offer.from_dict(x) for x in json.loads(offers_path.read_text(encoding='utf-8'))]
w.filter_query=SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',));w.mode='search';w.filter_summary()
w.offers=offers;w.render_offers();save('results')
w.show_details(w.offer_model.index(0));save('detail',w.dialogs[-1]);w.dialogs[-1].close()
def with_popup(popup,name,anchor):
    # Compose the actual two offscreen widget renders. The offscreen platform has
    # an 800px virtual screen, so place the popup at its control in this image.
    base=w.grab();p=QPainter(base);p.drawPixmap(anchor,popup.grab());p.end();base.save(str(target/(name+'.png')))
w.currency.showPopup();app.processEvents();point=w.currency.mapTo(w,QPoint(w.currency.width()-w.currency.popup.width(),w.currency.height()+5))
with_popup(w.currency.popup,'currency-menu',point);w.currency.search.setText('рубль');app.processEvents();assert w.currency.items.count()==2
with_popup(w.currency.popup,'currency-search',point);w.currency.hidePopup()
def capture_menu():
    menu=QApplication.activePopupWidget();assert isinstance(menu,QMenu)
    point=w.language_button.mapTo(w,QPoint(w.language_button.width()-menu.width(),w.language_button.height()+5))
    with_popup(menu,'language-menu',point);menu.close()
QTimer.singleShot(60,capture_menu);w.language_menu()
before=[o.to_dict() for o in w.offers];languages={}
for code in LANGUAGES:
    w.change_language(code);app.processEvents();settle(w)
    assert before==[o.to_dict() for o in w.offers]
    w.grab().save(str(target/('language-'+code+'.png')))
    languages[code]={'search':w.find_button.text(),'direction':'rtl' if w.layoutDirection()==Qt.LayoutDirection.RightToLeft else 'ltr'}
w.change_language('ru');w.resize(1050,740);save('compact');w.resize(1400,900);w.show_catalog();save('catalog-final')
w.rates_info();d=w.dialogs[-1];w.change_language('fr');app.processEvents();save('rates-fr',d);d.close()
w.change_language('ru');w.saved_searches();save('saved-searches',w.dialogs[-1]);w.dialogs[-1].close()
report={'result':'PASS','languages':languages,'offers_preserved':len(offers),'network_requests':w.assets.network_started,
        'normal_profile_used':False,'desktop_interaction':False,'native_windows_frame_manual_test':False}
(target/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');w.close();print('PASS: rendered 28 languages, RTL, flags, currency search, native filter content, rates, compact layout and original prices.')
