"""Live color-filter search in the UI; global scope is checked without crawling it."""
import os,sys,json,time
from pathlib import Path
from dataclasses import asdict
from collections import Counter
target=Path(sys.argv[1]).resolve();target.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['GIFT_FINDER_DATA_DIR']=str(target/'profile')
from PySide6.QtCore import QEventLoop,QTimer
from giftfinder.ui import MainWindow,application
from giftfinder.core import SearchQuery
from giftfinder.qa import settle
app=application();w=MainWindow(offline=True);w.show();w.change_language('ru');settle(w)
scopes={}
for color in ('black','green'):
    queries,_=w.catalog.resolve(SearchQuery(monochrome=True,mono_colors=(color,)))
    scopes[color]={'collections':len(queries),'models':sum(len(q.models) for q in queries)}
w.offline=False;reports=[]
for color,collection,model,backdrop in [('green','Input Key','Creeper','Malachite'),('black','Perfume Bottle','Noir','Black')]:
    w.open_filters('colors',SearchQuery(collection=collection,models=(model,),backdrops=(backdrop,),monochrome=True))
    d=w.filter_dialog;i=next(i for i,r in enumerate(d.rows.rows) if r['key']==color);d.choose(d.rows.index(i))
    started=time.monotonic();d.apply();loop=QEventLoop();timer=QTimer();timer.setInterval(40);ticks=[]
    def poll():
        ticks.append(time.monotonic()-started)
        if not w.busy:loop.quit()
    timer.timeout.connect(poll);timer.start();QTimer.singleShot(60000,loop.quit);loop.exec();timer.stop()
    assert not w.busy and w.result.progress['phase']=='complete'
    assert all(w.filter_query.matches(o) for o in w.offers)
    assert all(s.state in ('ok','no_match') and s.complete for s in w.result.statuses if s.source=='direct')
    assert w.result.progress['errors']==0 and len(ticks)>5
    settle(w);w.grab().save(str(target/(color+'-results.png')))
    reports.append({'color':color,'query':asdict(w.filter_query),'seconds':round(time.monotonic()-started,3),
        'offers':len(w.offers),'markets':dict(Counter(o.market for o in w.offers)),
        'direct':dict(Counter(o.market for o in w.offers if o.source=='direct')),'progress':w.result.progress,
        'ui_ticks':len(ticks),'statuses':[asdict(s) for s in w.result.statuses]})
    (target/(color+'-offers.json')).write_text(json.dumps([o.to_dict() for o in w.offers],ensure_ascii=False),encoding='utf8')
report={'result':'PASS','checked_at_utc':time.strftime('%Y-%m-%d %H:%M:%S UTC',time.gmtime()),'global_catalog_scopes':scopes,
    'global_network_crawl_performed':False,'searches':reports,'normal_profile_used':False,'desktop_interaction':False,'purchases':0}
(target/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');w.close()
print(json.dumps({'result':'PASS','global_catalog_scopes':scopes,'searches':[{k:r[k] for k in ('color','offers','direct','seconds')} for r in reports]}))
