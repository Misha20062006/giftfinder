import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QApplication

from giftfinder import platform_support
from giftfinder.core import Store
from giftfinder.design import font
from giftfinder.ui_common import application


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or application()


def test_profile_override_reuses_existing_settings_without_migration(tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path))
    old = Store(tmp_path)
    old.data['settings'] = {'language': 'ru', 'custom': {'keep': True}}
    old.data['searches'] = [{'collection': 'Easter Egg', 'models': ['Creeper']}]
    old.save()
    profile = platform_support.data_directory()
    assert profile == tmp_path
    assert Store(profile).data == old.data


def test_regular_profile_stays_at_existing_qt_location(app, monkeypatch):
    monkeypatch.delenv('GIFT_FINDER_DATA_DIR', raising=False)
    expected = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    assert platform_support.data_directory() == expected


def test_startup_error_profile_uses_override_without_importing_qt(tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path))
    import builtins
    original = builtins.__import__
    def no_qt(name, *args, **kwargs):
        if name.startswith('PySide6'):
            raise AssertionError('An isolated startup profile should not need Qt')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_qt)
    assert platform_support.data_directory() == tmp_path


def test_windows_fallback_keeps_legacy_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    assert platform_support.fallback_data_directory() == tmp_path / 'GiftFinder' / 'GiftFinder'


def test_missing_qt_uses_native_fallback_for_startup_errors(tmp_path, monkeypatch):
    import builtins
    monkeypatch.delenv('GIFT_FINDER_DATA_DIR', raising=False)
    monkeypatch.setattr(platform_support.sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    original = builtins.__import__
    def no_qt(name, *args, **kwargs):
        if name.startswith('PySide6'):
            raise ImportError('Qt dependency unavailable during startup')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', no_qt)
    assert platform_support.data_directory() == tmp_path / 'GiftFinder' / 'GiftFinder'


def test_macos_fallback_is_writable_user_data_not_app_bundle(monkeypatch):
    monkeypatch.setattr(platform_support.sys, 'platform', 'darwin')
    assert platform_support.fallback_data_directory() == Path.home() / 'Library' / 'Application Support' / 'GiftFinder' / 'GiftFinder'


def test_linux_fallback_honors_xdg_data_home(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_support.sys, 'platform', 'linux')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    assert platform_support.fallback_data_directory() == tmp_path / 'GiftFinder' / 'GiftFinder'
    monkeypatch.setenv('XDG_DATA_HOME', 'relative-data')
    assert platform_support.fallback_data_directory() == Path.home() / '.local' / 'share' / 'GiftFinder' / 'GiftFinder'


def test_custom_card_fonts_follow_application_font(app):
    original = app.font()
    try:
        selected = QFont('DejaVu Sans', 11)
        app.setFont(selected)
        font.cache_clear()
        card_font = font(17, QFont.Weight.DemiBold)
        assert card_font.family() == selected.family()
        assert card_font.pixelSize() == 17
        assert card_font.weight() == QFont.Weight.DemiBold
    finally:
        app.setFont(original)
        font.cache_clear()


def test_search_uses_platform_standard_find_shortcut(app, tmp_path, monkeypatch):
    monkeypatch.setenv('GIFT_FINDER_DATA_DIR', str(tmp_path))
    from PySide6.QtGui import QAction
    from giftfinder.ui import MainWindow
    window = MainWindow(offline=True)
    try:
        expected = QKeySequence(QKeySequence.StandardKey.Find)
        assert any(action.shortcut() == expected for action in window.findChildren(QAction))
    finally:
        window.close()
        app.processEvents()
