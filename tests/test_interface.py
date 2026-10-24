import os
os.environ['QT_QPA_PLATFORM']='offscreen'

import threading
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop,QTimer,QPersistentModelIndex,QSize,QObject,QEvent,Qt,QPointF,QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from giftfinder.ui_common import application,OfferModel
from giftfinder.previews import Assets,PreviewRenderer,asset_url
from giftfinder.catalogue import Catalog
from giftfinder.core import Offer
from giftfinder.design import MotionButton
from giftfinder.views import CardView


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


def wait_for(predicate,timeout=5000):
    if predicate():return
    loop=QEventLoop();timer=QTimer();timer.setInterval(10)
    timer.timeout.connect(lambda:loop.quit() if predicate() else None);timer.start();QTimer.singleShot(timeout,loop.quit);loop.exec();timer.stop()
    assert predicate(),'Qt operation did not complete'


def pause(ms):
    loop=QEventLoop();QTimer.singleShot(ms,loop.quit);loop.exec()


def row(n):
    return Offer(f'EasterEgg-{n}','Easter Egg',n,'fragment',Decimal(n),'TON','Creeper','Black',source='direct')


def test_png_loading_and_composition_run_outside_gui_and_share_cache(app,tmp_path,monkeypatch):
    import giftfinder.previews as previews
    main=threading.get_ident();reads=[];compositions=[]
    original=Path.is_file;compose=previews.compose
    def observed(path):
        reads.append(threading.get_ident());return original(path)
    def composed(*args):
        compositions.append(threading.get_ident());return compose(*args)
    monkeypatch.setattr(Path,'is_file',observed);monkeypatch.setattr(previews,'compose',composed)
    assets=Assets(tmp_path);assets.offline=True;renderer=PreviewRenderer(Catalog(tmp_path),assets)
    received=[];assets.ready.connect(lambda _:received.append(threading.get_ident()))
    url=asset_url('model','Easter Egg','Creeper')
    assert assets.get(url) is None
    assert not reads or all(t!=main for t in reads)
    wait_for(lambda:url in assets.cache)
    assert reads and all(t!=main for t in reads)
    assert received and all(t==main for t in received)
    key=renderer.key('Easter Egg','Creeper','Black','',224,218,1.,'https://nft.fragment.com/gift/easteregg-1.medium.jpg')
    other=renderer.key('Easter Egg','Creeper','Black','',224,218,1.,'https://nft.fragment.com/gift/easteregg-2.medium.jpg')
    assert key==other,'Unique gift numbers defeated the shared preview cache'
    renderer.request(key);wait_for(lambda:key in renderer.cache)
    assert compositions and all(t!=main for t in compositions)
    count=renderer.rendered
    for _ in range(30):assert renderer.request(key) is not None
    assert renderer.rendered==count
    hd=renderer.key('Easter Egg','Creeper','Black','',224,218,2.)
    renderer.request(hd);wait_for(lambda:hd in renderer.cache)
    assert renderer.cache[hd].size()==QSize(448,436) and renderer.cache[hd].devicePixelRatio()==2.


def test_price_updates_append_and_reorder_preserve_selection_without_reset(app):
    model=OfferModel();model.replace([row(1),row(2)]);persistent=QPersistentModelIndex(model.index(0));resets=[]
    model.modelReset.connect(lambda:resets.append(True))
    model.replace([replace(row(1),amount=Decimal('99')),row(2)])
    assert persistent.isValid() and persistent.data(Qt.ItemDataRole.UserRole).amount==99
    model.replace([replace(row(1),amount=Decimal('99')),row(2),row(3)])
    assert model.rowCount()==3 and persistent.row()==0
    model.replace([row(3),row(2),row(1)])
    assert persistent.isValid() and persistent.row()==2 and persistent.data(Qt.ItemDataRole.UserRole).number==1
    assert not resets


def test_unrelated_image_does_not_repaint_grid(app,tmp_path):
    assets=Assets(tmp_path);assets.offline=True;renderer=PreviewRenderer(Catalog(tmp_path),assets);view=CardView(renderer);view.resize(600,400)
    model=OfferModel();model.replace([row(1)]);view.setModel(model);view.show();app.processEvents()
    class Paints(QObject):
        count=0
        def eventFilter(self,obj,event):
            if event.type()==QEvent.Type.Paint:self.count+=1
            return False
    spy=Paints();view.viewport().installEventFilter(spy);app.processEvents();spy.count=0
    view.watch(('visible',),model.index(0));view.refresh_key(('unrelated',));app.processEvents();assert spy.count==0
    view.refresh_key(('visible',));app.processEvents();assert spy.count>0
    view.close()


def test_hover_animation_has_intermediate_state_and_does_not_delay_action(app,monkeypatch):
    from giftfinder import design
    monkeypatch.setattr(design,'motion_enabled',lambda:True)
    clicks=[];button=MotionButton('Найти',lambda:clicks.append(True),'primary');button.animate_to(1.)
    pause(55);assert 0<button.hover<1
    button.click();assert clicks==[True]
    wait_for(lambda:button.hover==1.);assert button.anim.state()==button.anim.State.Stopped


def test_wheel_scroll_animates_then_stops(app,tmp_path,monkeypatch):
    import giftfinder.views as views
    monkeypatch.setattr(views,'motion_enabled',lambda:True)
    assets=Assets(tmp_path);assets.offline=True;renderer=PreviewRenderer(Catalog(tmp_path),assets);view=CardView(renderer);view.resize(600,400)
    model=OfferModel();model.replace([row(i) for i in range(1,100)]);view.setModel(model);view.show();app.processEvents()
    event=QWheelEvent(QPointF(20,20),QPointF(20,20),QPoint(),QPoint(0,-120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
    view.wheelEvent(event);target=view.scroll_animation.endValue();assert target>0
    pause(65);assert 0<view.verticalScrollBar().value()<target
    wait_for(lambda:view.scroll_animation.state()==view.scroll_animation.State.Stopped)
    assert view.verticalScrollBar().value()==target
    view.close()


def test_reduced_motion_is_respected_without_changing_system_settings(app,monkeypatch):
    from giftfinder import design
    monkeypatch.setenv('GIFT_FINDER_REDUCED_MOTION','1');design.motion_enabled.cache_clear()
    try:
        button=MotionButton('Тест',lambda:None);button.animate_to(1.)
        assert button.hover==1. and button.anim.state()==button.anim.State.Stopped
    finally:design.motion_enabled.cache_clear()


def test_page_transition_blends_pages_and_does_not_block_input(app,monkeypatch):
    from PySide6.QtWidgets import QWidget
    from giftfinder import design
    monkeypatch.setattr(design,'motion_enabled',lambda:True)
    stack=design.MotionStack();stack.resize(300,200)
    red=QWidget();red.setStyleSheet('background:#ff0000;');blue=QWidget();blue.setStyleSheet('background:#0000ff;')
    stack.addWidget(red);stack.addWidget(blue);stack.show();app.processEvents();stack.setCurrentIndex(1)
    assert stack.currentIndex()==1 and stack.currentWidget().isEnabled()
    pause(65);color=stack.grab().toImage().pixelColor(150,100)
    assert color.red()>20 and color.blue()>20
    wait_for(lambda:stack.overlay is None);stack.close()
