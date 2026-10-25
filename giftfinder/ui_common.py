from __future__ import annotations

import json

import os

import sys

import threading

import time

from dataclasses import asdict

from decimal import Decimal, InvalidOperation

from pathlib import Path

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QObject, QRunnable, QSize,
                            Qt, QThreadPool, QTimer, QUrl, Signal, QRectF, QStandardPaths)

from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QFontDatabase, QIcon, QImageReader,
                           QKeySequence, QLinearGradient, QPainter, QPen, QPixmap)

from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
    QCompleter, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget,
    QStyledItemDelegate, QStyle, QVBoxLayout, QWidget)

from .core import (MARKETS, Offer, SearchQuery, SearchResult, Store, age_label, compact, csv_text,
                   fmt, merge_offers, norm, number, rub_value, safe_url, sorted_offers, ton_value)

from .providers import Catalog, SearchEngine, error_note, request

from .design import STYLE, MotionButton
from .i18n import EN, bind, tr, age_text


def label(text, name='', wrap=False):
    obj = QLabel(text)
    obj.setObjectName(name)
    obj.setWordWrap(wrap)
    obj.setTextFormat(Qt.TextFormat.PlainText)
    if text in EN:bind(obj,text)
    return obj

def button(text, callback, name='', glyph=''):
    return MotionButton(text,callback,name,glyph)


class TaskSignals(QObject):
    done = Signal(object)
    updated = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

class Task(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = TaskSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn(self.signals.progress.emit, self.signals.updated.emit))
        except Exception as error:
            message = str(error) if isinstance(error, ValueError) else error_note(error)
            self.signals.failed.emit(message)

class OfferModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.offers = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.offers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.offers):
            return None
        o = self.offers[index.row()]
        if role == Qt.ItemDataRole.SizeHintRole:
            return QSize(240, 354)
        if role == Qt.ItemDataRole.DisplayRole:
            return f'{o.collection} #{o.number} · {o.model} · {o.price_label}'
        if role == Qt.ItemDataRole.UserRole:
            return o
        if role == Qt.ItemDataRole.ToolTipRole:
            return f'{o.collection} #{o.number}\n{o.model} · {o.backdrop} · {o.symbol}\n{o.price_label}\n{age_text(o.checked_at)} · {o.source}'
        return None

    def replace(self, offers):
        old_keys=[o.key for o in self.offers];new_keys=[o.key for o in offers]
        if old_keys==new_keys:
            self.offers=offers
            if offers:self.dataChanged.emit(self.index(0),self.index(len(offers)-1),[Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.UserRole,Qt.ItemDataRole.ToolTipRole])
        elif old_keys and new_keys[:len(old_keys)]==old_keys:
            self.beginInsertRows(QModelIndex(),len(old_keys),len(new_keys)-1)
            self.offers=offers;self.endInsertRows()
            self.dataChanged.emit(self.index(0),self.index(len(old_keys)-1),[Qt.ItemDataRole.DisplayRole,Qt.ItemDataRole.UserRole,Qt.ItemDataRole.ToolTipRole])
        elif old_keys and set(old_keys)==set(new_keys):
            persistent=self.persistentIndexList();positions={key:i for i,key in enumerate(new_keys)}
            self.layoutAboutToBeChanged.emit();self.offers=offers
            self.changePersistentIndexList(persistent,[self.index(positions[old_keys[index.row()]]) for index in persistent])
            self.layoutChanged.emit()
        else:
            self.beginResetModel();self.offers=offers;self.endResetModel()

class SourceChip(QFrame):
    def __init__(self, market):
        super().__init__();self.market=market
        self.setStyleSheet('SourceChip { background: #212a33; border-radius: 8px; }')
        layout=QHBoxLayout(self);layout.setContentsMargins(11,7,11,7);layout.setSpacing(8)
        self.name=label(MARKETS[market][0]);self.name.setStyleSheet('color: '+MARKETS[market][1]+'; font-size: 12px; font-weight: 600;')
        self.info=label('—','tiny');self.info.setStyleSheet('color: #8d9baa; font-size: 11px;')
        layout.addWidget(self.name);layout.addStretch();layout.addWidget(self.info)

    def update_status(self,statuses,offers):
        rows=[o for o in offers if o.market==self.market];direct=sum(o.source=='direct' for o in rows)
        matching=[s for s in statuses if s.market==self.market]
        if direct:text,color=str(direct)+' '+tr('direct'),'#80cbb1'
        elif rows:text,color=str(len(rows))+' '+tr('index'),'#d7b77e'
        elif any(s.complete and s.source=='direct' for s in matching):text,color=tr('source_no_offers'),'#8e9caa'
        elif matching:text,color=tr('source_unavailable'),'#c9a56d'
        else:text,color='—','#718397'
        self.info.setText(text);self.info.setStyleSheet('color: '+color+'; font-size: 11px;')
        self.setToolTip('\n'.join(dict.fromkeys(f'{s.source}: {s.note} · {age_text(s.checked_at)}' for s in matching)) or tr('no_sources'))


def application():
    QApplication.setApplicationName('GiftFinder')
    QApplication.setOrganizationName('GiftFinder')
    QImageReader.setAllocationLimit(96)
    app = QApplication(sys.argv)
    if sys.platform == 'win32' and os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        fonts_dir = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
        for name in ('segoeui.ttf','segoeuib.ttf','segoeuil.ttf','seguisym.ttf','arial.ttf','tahoma.ttf',
                     'Nirmala.ttf','Nirmala.ttc','LeelawUI.ttf','msyh.ttc','malgun.ttf','YuGothM.ttc','meiryo.ttc'):
            if (fonts_dir/name).exists():QFontDatabase.addApplicationFont(str(fonts_dir/name))
    app.setStyle('Fusion')
    app.setFont(QFont('Segoe UI', 10) if sys.platform == 'win32'
                else QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont))
    return app
