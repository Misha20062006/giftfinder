"""Android entry point; desktop app.py remains a separate desktop application."""
import os
from pathlib import Path
import sys

ANDROID_SMOKE_IMAGE_URL = 'https://raw.githubusercontent.com/Misha20062006/giftfinder/f0a83fda1c99b46a273d9c01e86d71623d68792e/giftfinder/preview_seed/0052637187ec81a79ccb6849de38cba218de5c928185942594f45d95a6f47dd1.png'
ANDROID_SMOKE_IMAGE_SHA256 = '28eda0ef2eca93fe30f0cc829d12d168d3d72056761467d4db4c6dbc7b1dd385'

source_root = Path(__file__).resolve().parent.parent
if (source_root / 'giftfinder').is_dir():
    sys.path.insert(0, str(source_root))


def smoke_image_check(window):
    """Exercise Qt's real, uncached HTTPS image path without touching the profile."""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QImage
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    import hashlib

    request = QNetworkRequest(QUrl(ANDROID_SMOKE_IMAGE_URL))
    request.setTransferTimeout(20000)
    request.setAttribute(QNetworkRequest.Attribute.CacheLoadControlAttribute, QNetworkRequest.CacheLoadControl.AlwaysNetwork)
    request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
    manager = QNetworkAccessManager()
    reply = manager.get(request)
    loop = QEventLoop(); timer = QTimer(); timer.setSingleShot(True)
    reply.finished.connect(loop.quit)
    timer.timeout.connect(reply.abort); timer.timeout.connect(loop.quit)
    timer.start(30000)
    try:
        if not reply.isFinished(): loop.exec()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            raise RuntimeError('Android smoke HTTPS image failed: '+reply.errorString())
        if reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) != 200:
            raise RuntimeError('Android smoke image did not return HTTP 200')
        payload = bytes(reply.readAll())
        if hashlib.sha256(payload).hexdigest() != ANDROID_SMOKE_IMAGE_SHA256:
            raise RuntimeError('Android smoke HTTPS image checksum mismatch')
        image = QImage.fromData(payload)
        if image.isNull():
            raise RuntimeError('Android smoke HTTPS response is not a decodable image')
        return image.width(), image.height()
    finally:
        timer.stop(); reply.deleteLater(); manager.deleteLater()


def smoke_runtime_checks(window):
    """CI-only checks must fail before the application's READY marker."""
    from contextlib import closing
    import ssl
    import sqlite3
    import certifi
    import charset_normalizer
    from requests.models import chardet
    from PySide6.QtNetwork import QSslSocket

    context = ssl.create_default_context(cafile=certifi.where())
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError('Android smoke Python SSL context must verify certificates and hostnames')
    sample = 'GiftFinder — проверка кодировки UTF-8. Привет, мир!'
    if chardet is not charset_normalizer:
        raise RuntimeError('Android smoke requests must use the packaged charset_normalizer')
    encoding = chardet.detect(sample.encode('utf-8')).get('encoding')
    if not encoding or sample.encode('utf-8').decode(encoding) != sample:
        raise RuntimeError('Android smoke charset detection failed')
    print('GIFTFINDER_ANDROID_CHARSET_READY', flush=True)
    with closing(sqlite3.connect(':memory:')) as connection:
        if connection.execute('SELECT 1').fetchone() != (1,):
            raise RuntimeError('Android smoke SQLite query failed')
    print('GIFTFINDER_ANDROID_SQLITE_READY', flush=True)
    if not QSslSocket.supportsSsl():
        raise RuntimeError('Android smoke Qt TLS backend is unavailable')
    print('GIFTFINDER_ANDROID_TLS_READY', flush=True)
    width, height = smoke_image_check(window)
    if width <= 0 or height <= 0:
        raise RuntimeError('Android smoke image has invalid dimensions')
    print('GIFTFINDER_ANDROID_IMAGE_READY', flush=True)


def install_smoke_key_trace(window):
    """Observe CI Back dispatch before the ordinary window filter consumes it."""
    if os.environ.get('GIFT_FINDER_ANDROID_SMOKE') != '1':
        return None
    from PySide6.QtCore import QEvent, QObject, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    import json

    class KeyTrace(QObject):
        def eventFilter(self, target, event):
            if (event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
                    and event.key() in (Qt.Key.Key_Back, Qt.Key.Key_Escape)):
                record = {'type': event.type().name, 'key': Qt.Key(event.key()).name,
                          'target_class': target.metaObject().className(),
                          'target_name': target.objectName(),
                          'auto_repeat': event.isAutoRepeat(), 'count': event.count(),
                          'timestamp': event.timestamp(),
                          'input_method_visible': QGuiApplication.inputMethod().isVisible()}
                print('GIFTFINDER_ANDROID_KEY_EVENT ' + json.dumps(record, sort_keys=True), flush=True)
            return False

    observer = KeyTrace(window)
    window._android_smoke_key_observer = observer
    QApplication.instance().installEventFilter(observer)
    return observer


def main():
    from PySide6.QtCore import QTimer, Qt
    from giftfinder.mobile_ui import MobileWindow
    from giftfinder.ui_common import application

    app = application()
    if app.platformName() == 'android':
        # Qt's Android platform theme forwards this app-only hint to its status
        # and navigation bar appearance; it does not change the device theme.
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    smoke = os.environ.get('GIFT_FINDER_ANDROID_SMOKE') == '1'
    window = MobileWindow(offline=smoke)
    if smoke:
        install_smoke_key_trace(window)
        smoke_runtime_checks(window)
    window.show()
    QTimer.singleShot(250, lambda: print('GIFTFINDER_ANDROID_READY', flush=True))
    return app.exec()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        from giftfinder.platform_support import data_directory
        directory = data_directory(); directory.mkdir(parents=True, exist_ok=True)
        (directory / 'startup-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
        raise SystemExit(1)
