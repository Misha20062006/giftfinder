"""Read-only live checks with an isolated cache, no accounts or purchases."""
import json,sys,time
from pathlib import Path
from collections import Counter
from dataclasses import asdict
from giftfinder.catalogue import Catalog
from giftfinder.core import SearchQuery,sorted_offers
from giftfinder.providers import SearchEngine
target=Path(sys.argv[1]).resolve();target.mkdir(parents=True,exist_ok=True)
c=Catalog(target/'profile');engine=SearchEngine(c);reports=[]
queries=[SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',)),
 SearchQuery(collection='Input Key',models=('Creeper',),backdrops=('Malachite',),monochrome=True)]
for i,q in enumerate(queries):
    started=time.monotonic();snapshots=[]
    r=engine.search(q,on_update=lambda r:snapshots.append({'offers':len(r.offers),'progress':dict(r.progress)}))
    assert all(q.matches(o) for o in r.offers)
    assert r.progress['checked']==r.progress['total'] and r.progress['phase']=='complete'
    assert r.offers,'No live listings for selected test query'
    reports.append({'query':asdict(q),'seconds':round(time.monotonic()-started,2),'offers':len(r.offers),
        'markets':dict(Counter(o.market for o in r.offers)),'direct':dict(Counter(o.market for o in r.offers if o.source=='direct')),
        'progress':r.progress,'snapshots':snapshots,'warnings':r.warnings,'statuses':[asdict(s) for s in r.statuses]})
    (target/('offers.json' if i==0 else 'monochrome-offers.json')).write_text(json.dumps([o.to_dict() for o in sorted_offers(r.offers)],ensure_ascii=False),encoding='utf8')
    print(json.dumps({k:reports[-1][k] for k in ('query','seconds','offers','direct','progress')},ensure_ascii=False),flush=True)
(target/'verification.json').write_text(json.dumps({'checked_at_utc':time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()),'queries':reports,'normal_profile_used':False},ensure_ascii=False,indent=2),encoding='utf8')
