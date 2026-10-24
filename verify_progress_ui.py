"""Real asynchronous UI search and progress, offscreen and isolated."""
import os,sys,json,time
from pathlib import Path
target=Path(sys.argv[1]).resolve();target.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['GIFT_FINDER_DATA_DIR']=str(target/'profile')
from PySide6.QtCore import QEventLoop,QTimer
from giftfinder.ui import MainWindow,application
from giftfinder.core import SearchQuery
from giftfinder.qa import settle
app=application();w=MainWindow(offline=True);w.show();w.change_language('ru');settle(w)
w.offline=False;reports=[]
queries=[SearchQuery(collection='Easter Egg',models=('Creeper',),backdrops=('Black',)),SearchQuery(collection='Input Key',models=('Creeper',),backdrops=('Malachite',),monochrome=True)]
for n,q in enumerate(queries):
    w.filter_query=q;w.search_edit.clear();w.filter_summary();start=time.monotonic();w.start_search()
    loop=QEventLoop();timer=QTimer();timer.setInterval(25);ticks=[];frames=[]
    def poll():
        ticks.append(time.monotonic()-start);p=w.result.progress
        if w.progress_widget.isVisible() and p and p['checked']<p['total'] and p['checked']>0:
            frames.append(dict(p));w.grab().save(str(target/('loading-'+str(n)+'.png')))
        if not w.busy:loop.quit()
    timer.timeout.connect(poll);timer.start();QTimer.singleShot(60000,loop.quit);loop.exec();timer.stop()
    assert not w.busy and w.offers and all(q.matches(o) for o in w.offers)
    assert len(ticks)>5 and w.result.progress['phase']=='complete'
    assert w.progress_widget.isVisible() and w.progress_bar.value()==w.progress_bar.maximum()
    settle(w);w.grab().save(str(target/(('results' if n==0 else 'monochrome-results')+'.png')))
    reports.append({'query':n,'seconds':round(time.monotonic()-start,3),'offers':len(w.offers),'progress':w.result.progress,'ui_ticks':len(ticks),'partial_frames':frames})
w.show_catalog();w.resize(1050,740);app.processEvents();settle(w);w.grab().save(str(target/'all-themes-compact.png'))
w.resize(1400,900);w.open_filters('themes');app.processEvents();settle(w);w.filter_dialog.grab().save(str(target/'all-themes-filter.png'));w.filter_dialog.close()
(target/'verification.json').write_text(json.dumps({'result':'PASS','searches':reports,'normal_profile_used':False,'desktop_interaction':False,'purchases':0},ensure_ascii=False,indent=2),encoding='utf8')
w.close();print(json.dumps(reports))
