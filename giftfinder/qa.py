"""Offscreen QA utilities; never used to delay normal application work."""
from PySide6.QtCore import QEventLoop,QTimer


def settle(window,timeout=5000):
    loop=QEventLoop();timer=QTimer();timer.setInterval(25);quiet=0
    def check():
        nonlocal quiet
        animations=[getattr(window.stack,'transition',None)]+[getattr(d,'open_animation',None) for d in window.dialogs]
        active=any(a and a.state()==a.State.Running for a in animations)
        pending=window.assets.pending or window.assets.jobs or window.renderer.jobs
        quiet=quiet+1 if not pending and not active else 0
        if quiet>=2:loop.quit()
    timer.timeout.connect(check);timer.start();QTimer.singleShot(timeout,loop.quit);loop.exec();timer.stop()
