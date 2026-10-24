"""Real read-only UI search, offscreen, with an isolated application profile."""
import json
import os
import sys
import time
from pathlib import Path
from collections import Counter
from dataclasses import asdict

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
target = Path(sys.argv[1]).resolve(); target.mkdir(parents=True,exist_ok=True)
os.environ['GIFT_FINDER_DATA_DIR'] = str(target/'async-ui-profile')

from PySide6.QtCore import QEventLoop, QTimer
from giftfinder.core import SearchQuery
from giftfinder.ui import MainWindow, application
from giftfinder.qa import settle

app = application(); started = time.monotonic()
window = MainWindow(offline=True); startup = time.monotonic()-started
# Enable the requested live search only; do not trigger a second metadata refresh.
window.offline = False; window.assets.offline = False
window.filter_query = SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',))
window.filter_summary(); window.show()
window.refresh_rates()
started = time.monotonic(); first = None; heartbeat = 0
window.start_search()
loop = QEventLoop(); timer = QTimer(); timer.setInterval(50)
def poll():
    global first,heartbeat
    heartbeat += 1
    if window.offers and first is None: first = time.monotonic()-started
    if not window.busy: loop.quit()
timer.timeout.connect(poll); timer.start(); QTimer.singleShot(90000,loop.quit); loop.exec(); timer.stop()
duration = time.monotonic()-started
assert not window.busy,'Live search did not finish in 90 seconds'
assert window.offers,'No real offers returned'
assert all(o.model=='Creeper' and o.backdrop=='Black' for o in window.offers)
assert any(o.source=='direct' and o.market=='fragment' for o in window.offers)
assert any(o.source=='direct' and o.market=='portals' for o in window.offers)
assert heartbeat>5,'The main UI did not process events during search'
started = time.monotonic(); cached = window.engine.cached(window.filter_query); cache_ms = (time.monotonic()-started)*1000
assert len(cached.offers)==len(window.offers)
assert all(o.stale and o.source=='local-cache' for o in cached.offers)
wait_images = QEventLoop(); QTimer.singleShot(4500,wait_images.quit); wait_images.exec()
settle(window);window.grab().save(str(target/'actual-search.png'))
window.show_details(window.offer_model.index(0)); app.processEvents()
settle(window);window.dialogs[-1].grab().save(str(target/'detail.png')); window.dialogs[-1].close()
report = {'result':'PASS','startup_seconds':round(startup,3),'first_result_seconds':round(first or 0,3),
          'full_search_seconds':round(duration,3),'cached_search_ms':round(cache_ms,2),'ui_heartbeats':heartbeat,
          'total_offers':len(window.offers),'per_market':dict(Counter(o.market for o in window.offers)),
          'direct_offers':dict(Counter(o.market for o in window.offers if o.source=='direct')),
          'statuses':[asdict(s) for s in window.result.statuses], 'rates':window.ratebook.details(),
          'desktop_interaction':False,'profile':'isolated','purchases':0}
(target/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(target/'offers.json').write_text(json.dumps([o.to_dict() for o in window.offers],ensure_ascii=False),encoding='utf-8')
window.close()
print(json.dumps({k:report[k] for k in ('result','first_result_seconds','full_search_seconds','cached_search_ms','total_offers','per_market','direct_offers')},ensure_ascii=False))
