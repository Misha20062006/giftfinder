import json,sys,time,threading
from pathlib import Path
from collections import Counter
from giftfinder.catalogue import Catalog
from giftfinder.core import SearchQuery
from giftfinder.providers import SearchEngine
p=Path(sys.argv[1]);p.mkdir(parents=True,exist_ok=True)
c=Catalog(p/'pages-profile'); engine=SearchEngine(c); updates=[]; stop=threading.Event()
timer=threading.Timer(90,stop.set);timer.start();started=time.monotonic()
try:
 result=engine.search(SearchQuery(collection='Easter Egg',models=('Creeper','Chicken','Baby Chick','Baby Turtle','Choco Bunny','Early Bird','Easter Bunny','Foliage'),markets=('fragment','portals')),cancelled=stop,on_update=lambda r: updates.append({'offers':len(r.offers),'direct':dict(Counter(o.market for o in r.offers if o.source=='direct')),'more':any(s.has_more for s in r.statuses if s.source=='direct')}))
finally:timer.cancel()
report={'seconds':round(time.monotonic()-started,2),'cancelled':stop.is_set(),'updates':updates,'direct':dict(Counter(o.market for o in result.offers if o.source=='direct')),'complete':{s.market:s.complete for s in result.statuses if s.source=='direct'},'warnings':result.warnings}
(p/'automatic-pages.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
assert not stop.is_set()
assert all(s.complete for s in result.statuses if s.source=='direct')
assert any(u['more'] for u in updates), 'Query did not require additional pages'
assert len({o.key for o in result.offers})==len(result.offers)


