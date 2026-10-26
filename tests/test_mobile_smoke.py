import hashlib
import json
from pathlib import Path
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtWidgets import QApplication
from PySide6 import QtNetwork
from PySide6.QtGui import QImage
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QComboBox, QDialog, QWidget
from giftfinder.ui_common import application
from mobile import main as entry


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


def mock_image_transport(monkeypatch, payload):
    captured = {}
    class Finished:
        def connect(self, callback): pass
    class Reply:
        finished = Finished()
        def isFinished(self): return True
        def error(self): return QtNetwork.QNetworkReply.NetworkError.NoError
        def attribute(self, attribute): return 200
        def readAll(self): return payload
        def abort(self): pass
        def deleteLater(self): captured['reply_closed'] = True
    class Manager:
        def get(self, request):
            captured['request'] = request
            return Reply()
        def deleteLater(self): captured['manager_closed'] = True
    monkeypatch.setattr(QtNetwork, 'QNetworkAccessManager', Manager)
    return captured


def test_https_probe_checks_pinned_image_digest_and_keeps_network_and_tls_defaults(app, monkeypatch):
    seed = Path(__file__).resolve().parents[1] / 'giftfinder/preview_seed/0052637187ec81a79ccb6849de38cba218de5c928185942594f45d95a6f47dd1.png'
    payload = seed.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == entry.ANDROID_SMOKE_IMAGE_SHA256
    captured = mock_image_transport(monkeypatch, payload)
    image = QImage.fromData(payload)
    assert entry.smoke_image_check(None) == (image.width(), image.height())
    request = captured['request']
    assert request.url().toString() == entry.ANDROID_SMOKE_IMAGE_URL
    assert request.attribute(QtNetwork.QNetworkRequest.Attribute.CacheLoadControlAttribute) == QtNetwork.QNetworkRequest.CacheLoadControl.AlwaysNetwork
    assert request.attribute(QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute) == QtNetwork.QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
    assert request.sslConfiguration().peerVerifyMode() != QtNetwork.QSslSocket.PeerVerifyMode.VerifyNone
    assert captured['reply_closed'] and captured['manager_closed']


def test_https_probe_rejects_an_altered_but_decodable_image(app, monkeypatch):
    seed = Path(__file__).resolve().parents[1] / 'giftfinder/preview_seed/0052637187ec81a79ccb6849de38cba218de5c928185942594f45d95a6f47dd1.png'
    altered = seed.read_bytes() + b'altered payload'
    assert not QImage.fromData(altered).isNull()
    captured = mock_image_transport(monkeypatch, altered)
    with pytest.raises(RuntimeError, match='checksum mismatch'):
        entry.smoke_image_check(None)
    assert captured['reply_closed'] and captured['manager_closed']


def test_key_trace_requires_explicit_smoke_mode(app, monkeypatch):
    monkeypatch.delenv('GIFT_FINDER_ANDROID_SMOKE', raising=False)
    window = QWidget()
    try:
        assert entry.install_smoke_key_trace(window) is None
        assert not hasattr(window, '_android_smoke_key_observer')
    finally:
        window.deleteLater()


def test_key_trace_observes_before_normal_filter_without_consuming_or_changing_events(app, monkeypatch, capsys):
    monkeypatch.setenv('GIFT_FINDER_ANDROID_SMOKE', '1')
    window = QWidget()
    received = []
    before_normal = []

    class Receiver(QObject):
        def event(self, event):
            if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                received.append((event.key(), event.isAccepted()))
                return True
            return super().event(event)

    class NormalFilter(QObject):
        def eventFilter(self, target, event):
            if target is receiver and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                before_normal.append(capsys.readouterr().out)
            return False

    receiver = Receiver(window); receiver.setObjectName('diagnosticTarget')
    normal = NormalFilter(window)
    app.installEventFilter(normal)
    observer = entry.install_smoke_key_trace(window)
    try:
        assert window._android_smoke_key_observer is observer and observer.parent() is window
        for event_type, key in ((QEvent.Type.KeyPress, Qt.Key.Key_Back),
                                (QEvent.Type.KeyRelease, Qt.Key.Key_Back),
                                (QEvent.Type.KeyPress, Qt.Key.Key_Escape),
                                (QEvent.Type.KeyRelease, Qt.Key.Key_Escape),
                                (QEvent.Type.KeyPress, Qt.Key.Key_A)):
            event = QKeyEvent(event_type, key, Qt.KeyboardModifier.NoModifier, '', True, 2)
            event.setTimestamp(12345)
            event.ignore()
            app.sendEvent(receiver, event)
        assert received == [(key, False) for key in
                            (Qt.Key.Key_Back, Qt.Key.Key_Back, Qt.Key.Key_Escape, Qt.Key.Key_Escape, Qt.Key.Key_A)]
        assert before_normal[-1] == ''
        records = [json.loads(line.removeprefix('GIFTFINDER_ANDROID_KEY_EVENT '))
                   for output in before_normal[:-1] for line in output.splitlines()]
        assert [(r['type'], r['key']) for r in records] == [
            ('KeyPress', 'Key_Back'), ('KeyRelease', 'Key_Back'),
            ('KeyPress', 'Key_Escape'), ('KeyRelease', 'Key_Escape')]
        assert all(r['target_class'] == receiver.metaObject().className() and r['target_name'] == 'diagnosticTarget'
                   and r['auto_repeat'] and r['count'] == 2 and r['timestamp'] == 12345
                   and r['input_method_visible'] == app.inputMethod().isVisible() for r in records), records
    finally:
        app.removeEventFilter(observer)
        app.removeEventFilter(normal)
        window.deleteLater()


def test_category_trace_observes_pointer_and_post_dispatch_focus_without_changing_events(app, monkeypatch, capsys):
    monkeypatch.setenv('GIFT_FINDER_ANDROID_SMOKE', '1')
    window = QWidget(); dialog = QDialog(window)
    received = []

    class Category(QComboBox):
        def event(self, event):
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
                received.append(event.isAccepted())
                return True
            return super().event(event)

    category = Category(dialog); category.setGeometry(10, 10, 200, 48)
    category.addItem('Collection', 'collections')
    dialog.category_select = category; window.filter_dialog = dialog
    window.show(); dialog.show(); app.processEvents()
    observer = entry.install_smoke_key_trace(window)
    try:
        point = QPointF(20, 20); global_point = QPointF(category.mapToGlobal(QPoint(20, 20)))
        for event_type, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton),
                                    (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
            event = QMouseEvent(event_type, point, global_point, Qt.MouseButton.LeftButton,
                                buttons, Qt.KeyboardModifier.NoModifier)
            event.setTimestamp(12345); event.ignore()
            app.sendEvent(category, event)
        app.processEvents()
        assert received == [False, False]
        output = capsys.readouterr().out.splitlines()
        records = [json.loads(line.removeprefix('GIFTFINDER_ANDROID_CATEGORY_EVENT '))
                   for line in output if line.startswith('GIFTFINDER_ANDROID_CATEGORY_EVENT ')]
        snapshots = [json.loads(line.removeprefix('GIFTFINDER_ANDROID_CATEGORY_AFTER '))
                     for line in output if line.startswith('GIFTFINDER_ANDROID_CATEGORY_AFTER ')]
        category_records = [r for r in records if r['target']['class'] == category.metaObject().className()]
        assert [r['type'] for r in category_records] == ['MouseButtonPress', 'MouseButtonRelease']
        assert all(r['local'] == [20, 20] and r['global'] == [global_point.x(), global_point.y()]
                   and r['timestamp'] == 12345 and r['target']['class'] == category.metaObject().className()
                   and r['focus_on_touch_release'] == app.styleHints().setFocusOnTouchRelease()
                   for r in category_records)
        assert [r['after_type'] for r in snapshots] == [r['type'] for r in records]
        assert all(r['category_has_focus'] == category.hasFocus() and r['popup'] is None for r in snapshots)
    finally:
        app.removeEventFilter(observer)
        window.filter_dialog = None
        dialog.close(); window.close(); window.deleteLater()
