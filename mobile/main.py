"""Android entry point; desktop app.py remains a separate desktop application."""
import os
from pathlib import Path
import sys

source_root = Path(__file__).resolve().parent.parent
if (source_root / 'giftfinder').is_dir():
    sys.path.insert(0, str(source_root))


def smoke_image_check(window):
    """Exercise Qt's real, uncached HTTPS image path without touching the profile."""
    from PySide6.QtCore import QEventLoop, QTimer, QUrl
    from PySide6.QtGui import QImage
    from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
    from giftfinder.previews import asset_url

    rows = window.catalog.model_rows
    row = next((value for value in rows if value['collection'] == 'Easter Egg' and value['name'] == 'Creeper'), rows[0])
    request = QNetworkRequest(QUrl(asset_url('model', row['collection'], row['name'], 128)))
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
        image = QImage.fromData(bytes(reply.readAll()))
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
    from PySide6.QtNetwork import QSslSocket

    context = ssl.create_default_context(cafile=certifi.where())
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError('Android smoke Python SSL context must verify certificates and hostnames')
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
