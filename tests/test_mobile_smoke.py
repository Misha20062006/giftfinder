import pytest
from PySide6.QtNetwork import QSslSocket

from mobile import main as entry


def test_smoke_rejects_missing_qt_tls_before_image_or_ready(monkeypatch, capsys):
    monkeypatch.setattr(QSslSocket, 'supportsSsl', lambda: False)
    monkeypatch.setattr(entry, 'smoke_image_check', lambda window: pytest.fail('A missing TLS backend must not start an image request'))
    with pytest.raises(RuntimeError, match='TLS backend is unavailable'):
        entry.smoke_runtime_checks(None)
    output = capsys.readouterr().out
    assert 'GIFTFINDER_ANDROID_SQLITE_READY' in output
    assert 'GIFTFINDER_ANDROID_TLS_READY' not in output
    assert 'GIFTFINDER_ANDROID_READY' not in output


def test_smoke_does_not_report_image_success_after_failed_https(monkeypatch, capsys):
    monkeypatch.setattr(QSslSocket, 'supportsSsl', lambda: True)
    def failed(window): raise RuntimeError('Image TLS handshake failed')
    monkeypatch.setattr(entry, 'smoke_image_check', failed)
    with pytest.raises(RuntimeError, match='TLS handshake failed'):
        entry.smoke_runtime_checks(None)
    output = capsys.readouterr().out
    assert 'GIFTFINDER_ANDROID_TLS_READY' in output
    assert 'GIFTFINDER_ANDROID_IMAGE_READY' not in output
    assert 'GIFTFINDER_ANDROID_READY' not in output


def test_smoke_success_requires_nonempty_decoded_image(monkeypatch, capsys):
    monkeypatch.setattr(QSslSocket, 'supportsSsl', lambda: True)
    monkeypatch.setattr(entry, 'smoke_image_check', lambda window: (128,128))
    entry.smoke_runtime_checks(None)
    output = capsys.readouterr().out
    assert 'GIFTFINDER_ANDROID_SQLITE_READY' in output
    assert 'GIFTFINDER_ANDROID_TLS_READY' in output
    assert 'GIFTFINDER_ANDROID_IMAGE_READY' in output
    assert 'GIFTFINDER_ANDROID_READY' not in output
