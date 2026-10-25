"""Desktop integration shared by normal startup and early error reporting."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def data_directory() -> Path:
    """Use the existing Qt application profile, including isolated QA overrides."""
    override = os.environ.get('GIFT_FINDER_DATA_DIR')
    if override:
        return Path(override)
    try:
        from PySide6.QtCore import QCoreApplication, QStandardPaths

        QCoreApplication.setApplicationName('GiftFinder')
        QCoreApplication.setOrganizationName('GiftFinder')
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if location:
            return Path(location)
    except ImportError:
        # A missing Qt dependency must not redirect startup logs into the app bundle.
        pass
    return fallback_data_directory()


def fallback_data_directory() -> Path:
    """Resolve the same desktop profile family when Qt cannot be imported yet."""
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local')
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        xdg_data = os.environ.get('XDG_DATA_HOME', '')
        # The XDG specification defines relative values as invalid.
        base = Path(xdg_data) if xdg_data and Path(xdg_data).is_absolute() else Path.home() / '.local' / 'share'
    return base / 'GiftFinder' / 'GiftFinder'
