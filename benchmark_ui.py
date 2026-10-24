"""Offscreen rendering/scroll benchmark; never touches the normal app profile."""
import argparse
import cProfile
import json
import os
import pstats
import io
import time
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--source');parser.add_argument('--profile',action='store_true');args=parser.parse_args()
target=Path(args.output).resolve();target.mkdir(parents=True,exist_ok=True)
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['GIFT_FINDER_DATA_DIR']=str(target/'profile')
if args.source:
    import sys
    sys.path.insert(0,str(Path(args.source).resolve()))
from PySide6.QtCore import QEventLoop,QTimer,Qt
from giftfinder.ui import MainWindow,application
from giftfinder.core import Offer,SearchQuery

app=application();w=MainWindow(offline=True);w.show();app.processEvents()
profiler=cProfile.Profile();steps=[];gaps=[];last=time.perf_counter()
def heartbeat():
    global last
    now=time.perf_counter();gaps.append((now-last)*1000);last=now
beat=QTimer();beat.setInterval(8);beat.timeout.connect(heartbeat);beat.start()
loop=QEventLoop();phase=0;step=0
members=[pair for theme in w.catalog.themes.values() for pair in theme['members']]
backdrops=list(w.catalog.backdrop_lookup.values())
offers=[Offer(f'{c.replace(" ","")}-{i+1}',c,i+1,'fragment',Decimal(str(i+1)),'TON',m,
              backdrops[i%len(backdrops)]['name'],source='direct',checked_at=1700000000) for i,(c,m) in enumerate((members*20)[:2400])]
updates=[[replace(o,amount=o.amount+Decimal(delta)) for o in offers] for delta in ('0.01','0.02')]
last=time.perf_counter()
if args.profile:profiler.enable()
def tick():
    global phase,step
    started=time.perf_counter()
    if phase==0:
        bar=w.home_grid.verticalScrollBar();bar.setValue(round(bar.maximum()*((step%20)/19)))
        w.home_grid.viewport().repaint()
        if step==39:
            w.mode='search';w.offers=offers;w.render_offers();phase=1;step=-1
    else:
        bar=w.view.verticalScrollBar();bar.setValue(round(bar.maximum()*((step%30)/29)))
        if step%6==0:
            w.offers=updates[(step//6)%2]
            w.render_offers()
        w.view.viewport().repaint()
        if step==89:loop.quit()
    steps.append({'phase':phase,'ms':(time.perf_counter()-started)*1000});step+=1
timer=QTimer();timer.setInterval(16);timer.timeout.connect(tick);timer.start();QTimer.singleShot(20000,loop.quit);loop.exec();timer.stop();beat.stop();profiler.disable()
def stats(values):
    s=sorted(values)
    return {'count':len(s),'p50_ms':round(s[len(s)//2],2),'p95_ms':round(s[min(len(s)-1,int(len(s)*.95))],2),'max_ms':round(max(s),2),'over_50_ms':sum(v>50 for v in s)} if s else {}
report={'scroll_steps':stats([s['ms'] for s in steps]),'event_loop_gaps':stats(gaps),
        'catalog':stats([s['ms'] for s in steps if s['phase']==0]),'offers':stats([s['ms'] for s in steps if s['phase']==1]),'offers_count':len(offers),'desktop_interaction':False}
stream=io.StringIO()
if args.profile:pstats.Stats(profiler,stream=stream).strip_dirs().sort_stats('cumtime').print_stats(35)
(target/'profile.txt').write_text(stream.getvalue(),encoding='utf-8');(target/'benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8');w.close();print(json.dumps(report))
