"""Deterministic offscreen user scenarios, with real offers saved by verify_async_ui."""
import json
import os
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

os.environ['QT_QPA_PLATFORM']='offscreen'
target=Path(sys.argv[1]).resolve(); target.mkdir(parents=True,exist_ok=True)
os.environ['GIFT_FINDER_DATA_DIR']=str(target/'ui-profile')

from PySide6.QtCore import Qt,QPointF
from giftfinder.core import Offer,SearchQuery,SearchResult,SourceStatus,Store
from giftfinder.ui import MainWindow,application
from giftfinder.qa import settle

app=application(); window=MainWindow(offline=True); window.show(); app.processEvents();settle(window)
window.grab().save(str(target/'catalog.png'))
data=json.loads((target/'offers.json').read_text(encoding='utf-8'))
rows=[Offer.from_dict(r) for r in data]
report=json.loads((target/'verification.json').read_text(encoding='utf-8'))
window.filter_query=SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',))
window.currency.setCurrentIndex(window.currency.findData('RUB'))
window.filter_summary(); window.mode='search'
result=SearchResult(rows,[SourceStatus(**r) for r in report['statuses']],scope='Easter Egg · Creeper · Black')
window.accept_result(result,window.generation,True); app.processEvents();settle(window)
assert window.offer_model.rowCount()==len(rows)
window.grab().save(str(target/'results-rub.png'))
original=[(o.key,o.amount,o.currency) for o in rows]
for code in ('USD','EUR','JPY','RUB','Stars','ORIGINAL'):
    window.currency.setCurrentIndex(window.currency.findData(code)); app.processEvents()
    assert window.offer_model.rowCount()==len(rows)
assert original==[(o.key,o.amount,o.currency) for o in rows]
window.currency.setCurrentIndex(window.currency.findData('USD')); app.processEvents()
window.grab().save(str(target/'results-usd.png'))
window.show_details(window.offer_model.index(0)); detail=window.dialogs[-1]; app.processEvents();settle(window)
detail.grab().save(str(target/'detail.png'))
if detail.offer.key in window.store.data['favorites']: detail.toggle_favorite()
detail.toggle_favorite(); assert detail.offer.key in Store(window.data_dir).data['favorites']
detail.close(); window.show_favorites(); assert window.offer_model.rowCount()>=1
window.mode='search'; window.offers=rows; window.render_offers()
window.open_filters('models'); dialog=window.filter_dialog; app.processEvents();settle(window)
assert len(dialog.all_rows)==len(window.catalog.data['traits']['Easter Egg']['models'])
dialog.grab().save(str(target/'filters-models.png'))
dialog.change_tab('backdrops'); app.processEvents();settle(window); assert len(dialog.all_rows)==80
dialog.grab().save(str(target/'filters-backdrops.png'))
dialog.change_tab('symbols'); assert len(dialog.all_rows)>100
dialog.change_tab('themes'); app.processEvents();settle(window); assert len(dialog.all_rows)==10
dialog.grab().save(str(target/'filters-themes.png'))
# Exercise the same drag event handlers, without moving the physical pointer.
class Event:
    def __init__(self,x,y):self.point=QPointF(x,y)
    def button(self):return Qt.MouseButton.LeftButton
    def buttons(self):return Qt.MouseButton.LeftButton
    def globalPosition(self):return self.point
    def accept(self):pass
before=dialog.pos(); dialog.header.mousePressEvent(Event(before.x()+30,before.y()+20))
dialog.header.mouseMoveEvent(Event(before.x()+120,before.y()+70)); dialog.header.mouseReleaseEvent(Event(0,0))
assert dialog.pos().x()==before.x()+90 and dialog.pos().y()==before.y()+50
dialog.resize(900,680); assert dialog.width()==900 and dialog.height()==680
dialog.close(); assert window.filter_dialog is None
# A decimal comma in the price range must stay a decimal fraction.
window.filter_extra={'min':'1,5','max':'2,5','unit':'GRAM'}
window.offers=[replace(rows[0],amount=Decimal('2'),currency='TON'),replace(rows[0],slug='EasterEgg-9999999',amount=Decimal('20'),currency='TON')]
window.render_offers(); assert window.offer_model.rowCount()==1
window.filter_extra={}; window.offers=rows; window.sort.setCurrentIndex(1); window.render_offers()
prices=[window.ratebook.usd(o) for o in window.offer_model.offers]
assert prices==sorted(prices,reverse=True)
window.save_search(); assert Store(window.data_dir).data['searches']
window.saved_searches(); app.processEvents(); window.dialogs[-1].close()
window.resize(1050,740); app.processEvents(); window.grab().save(str(target/'compact.png'))
assert window.filter_button.geometry().left()>window.search_edit.geometry().left()
window.close()
print('PASS: full local selectors, images, currencies including Stars, immutable original prices, exact filters, decimal comma, floating drag/resize, favorites/profile, saved searches, compact layout')
