"""The same explicit update action in desktop and touch interfaces."""
from pathlib import Path
import sys
import threading
import os

from PySide6.QtCore import QObject, QStandardPaths
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar

from . import __version__
from . import updates
from .i18n import tr
from .ui_common import button


class UpdateController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.release = None
        self.checking = False
        self.downloading = False
        self.dialog = None
        self.cancelled = threading.Event()

    def show(self):
        if self.dialog is not None:
            self.dialog.raise_()
            return
        dialog = QDialog(self.window)
        dialog.setWindowTitle(tr('app_updates'))
        dialog.resize(480, 230)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f'GiftFinder {__version__}'))
        self.message = QLabel(tr('update_checking'))
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.install = button('install_update', self.start, 'primary')
        self.install.setEnabled(False)
        layout.addWidget(self.install)
        layout.addWidget(button('cancel', dialog.close))
        self.dialog = dialog
        dialog.finished.connect(self.closed)
        self.window.keep_dialog(dialog)
        if self.release:
            self.ready(self.release)
        elif not self.downloading:
            self.check()

    def check(self):
        if self.checking or self.downloading or self.window.closing:
            return
        self.checking = True
        if self.dialog:
            self.message.setText(tr('update_checking'))
            self.install.setEnabled(False)
        self.window.task(lambda _: updates.check_release(), self.ready, self.failed)

    def closed(self, _):
        self.dialog = None
        self.cancelled.set()

    def ready(self, release):
        self.checking = False
        if self.window.closing:
            return
        self.release = release
        self.window.update_button.setText(tr('update_available', version=release.version) if release else tr('app_updates'))
        if self.window.update_button.property('mobileUpdate'):
            self.window.update_button.setVisible(release is not None)
        if self.dialog:
            self.message.setText(tr('update_description', version=release.version) if release else tr('update_current'))
            self.install.setEnabled(release is not None)

    def failed(self, _):
        self.checking = False
        self.downloading = False
        if self.dialog and not self.window.closing:
            self.message.setText(tr('update_failed'))
            self.install.setEnabled(self.release is not None)
            self.progress.hide()

    def start(self):
        if self.downloading or not self.release:
            return
        self.downloading = True
        self.cancelled.clear()
        self.install.setEnabled(False)
        self.message.setText(tr('update_downloading'))
        self.progress.setValue(0)
        self.progress.show()
        cache = os.environ.get('GIFT_FINDER_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        directory = Path(cache) / 'updates'
        release = self.release
        self.window.task(lambda emit: updates.download_release(release, directory, lambda value: emit(str(value)), self.cancelled.is_set),
                         self.downloaded, self.failed, progress=self.download_progress)

    def download_progress(self, percent):
        if self.dialog:
            self.progress.setValue(int(percent))

    def downloaded(self, path):
        self.downloading = False
        if self.window.closing or self.cancelled.is_set():
            return
        try:
            if not updates.launch_installer(path):
                raise RuntimeError('The system did not accept the installer')
        except Exception:
            self.failed(None)
            return
        if sys.platform == 'win32':
            self.window.close()
        elif self.dialog:
            self.message.setText(tr('update_opened'))
            self.progress.hide()
