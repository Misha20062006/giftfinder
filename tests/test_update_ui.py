import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import copy
import hashlib

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from giftfinder import updates
from giftfinder.ui import MainWindow
from giftfinder.mobile_ui import MobileWindow
from giftfinder.ui_common import application


@pytest.fixture(params=[MainWindow, MobileWindow])
def window(request, tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path))
    app = QApplication.instance() or application()
    window = request.param(offline=True)
    window.show();app.processEvents()
    yield window
    window.close();app.processEvents()


def future_release():
    name = 'GiftFinder-0.10.0-Windows-x64-Setup.exe'
    return updates.Release('0.10.0', name, updates.PREFIX+'v0.10.0/'+name,
                           hashlib.sha256(b'installer').hexdigest(), len(b'installer'))


def test_discovery_and_cancel_never_launch_an_installer_or_change_settings(window, monkeypatch):
    before = copy.deepcopy(window.store.data)
    launches = []
    monkeypatch.setattr(updates, 'launch_installer', lambda path: launches.append(path))
    controller = window.updates
    controller.ready(future_release())
    controller.show()
    assert controller.install.isEnabled() and launches == []
    monkeypatch.setattr(window, 'task', lambda *args, **kwargs: None)
    controller.start()
    controller.dialog.close()
    controller.downloaded('cancelled-installer.exe')
    assert launches == [] and window.isVisible()
    assert window.store.data == before


def test_real_worker_download_hands_off_only_the_verified_installer(window, monkeypatch, tmp_path):
    class Response:
        url = 'https://release-assets.githubusercontent.com/installer'
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_content(self, size): yield b'installer'
    monkeypatch.setattr(updates.requests, 'get', lambda *args, **kwargs: Response())
    launches = []
    monkeypatch.setattr(updates, 'launch_installer', lambda path: (launches.append(path), True)[1])
    controller = window.updates
    controller.ready(future_release());controller.show();controller.start()
    for _ in range(100):
        QTest.qWait(20)
        if launches:
            break
    assert len(launches) == 1
    assert launches[0].is_relative_to(tmp_path)
    assert launches[0].read_bytes() == b'installer'
