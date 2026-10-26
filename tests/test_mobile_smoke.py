import hashlib
from pathlib import Path
import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import pytest
from PySide6.QtWidgets import QApplication
from PySide6 import QtNetwork
from PySide6.QtGui import QImage
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
