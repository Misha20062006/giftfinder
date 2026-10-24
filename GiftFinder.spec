# Reproducible one-file Windows build. Run with PyInstaller from this directory.
from pathlib import Path

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'app.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'giftfinder' / 'catalog_seed.json'), 'giftfinder'),
           (str(root / 'giftfinder' / 'catalog_full.json'), 'giftfinder'),
           (str(root / 'giftfinder' / 'themes_curated.json'), 'giftfinder'),
           (str(root / 'giftfinder' / 'monochrome_pairs.json'), 'giftfinder'),
           (str(root / 'giftfinder' / 'rates_seed.json'), 'giftfinder'),
           (str(root / 'giftfinder' / 'preview_seed'), 'giftfinder/preview_seed'),
           (str(root / 'giftfinder' / 'locales'), 'giftfinder/locales'),
           (str(root / 'giftfinder' / 'flags'), 'giftfinder/flags'),
           (str(root / 'giftfinder' / 'icon.png'), 'giftfinder')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.QtWebEngineQuick','PySide6.QtWebView',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtOpenGL', 'PySide6.QtSql',
              'PySide6.QtTest', 'PySide6.QtXml', 'PySide6.QtPrintSupport', 'PySide6.QtDBus'],
    noarchive=False,
)
# Qt 6.12 uses Windows' unversioned ICU entry points. The build host's
# Poppler directory is on PATH and has a different icuuc.dll with ICU 78
# suffixed exports. Do not package that unrelated DLL; use the OS ICU,
# exactly as the installed Qt wheel does on Windows 10/11.
a.binaries = [entry for entry in a.binaries
              if Path(entry[1]).name.casefold() not in {'icuuc.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='GiftFinder', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
    icon=str(root / 'giftfinder' / 'icon.ico'),
    version=str(root / 'version-info.txt'),
)
