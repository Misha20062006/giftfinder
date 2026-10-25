"""Touch layouts for Android, sharing the desktop search and profile implementation."""
from __future__ import annotations

import csv
from dataclasses import replace
import io
import os

from PySide6.QtCore import QEvent, QFile, QIODevice, QPoint, QRect, QRectF, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QLayout, QListView, QListWidget, QListWidgetItem, QMenu,
    QScrollArea, QScroller, QSizeGrip, QSizePolicy, QStyledItemDelegate, QVBoxLayout, QWidget)

from .controls import SearchSelector
from .core import MARKETS, safe_url
from .design import MotionButton, font
from .i18n import LANGUAGES, age_text, bind, language_code, message, refresh_tree, tr
from .icons import flag_icon
from .selectors import FilterDialog
from .ui import DetailsDialog, MainWindow, date_text
from .ui_common import button, label


def touch(widget, height=48):
    widget.setMinimumSize(0, height)
    widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
    return widget


def steal_layout(widget):
    """Keep desktop-only controls alive while replacing their containing layout."""
    stash = QWidget(widget)
    stash.setLayout(widget.layout())
    stash.hide()
    return stash


def list_view(view, delegate, height):
    view.setViewMode(QListView.ViewMode.ListMode)
    view.setFlow(QListView.Flow.TopToBottom)
    view.setWrapping(False)
    view.setItemDelegate(delegate)
    view.setGridSize(QSize(max(1, view.viewport().width()), height))
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    QScroller.grabGesture(view.viewport(), QScroller.ScrollerGestureType.TouchGesture)


class MobileTileDelegate(QStyledItemDelegate):
    def __init__(self, renderer, parent, selected=lambda row: False):
        super().__init__(parent)
        self.renderer = renderer
        self.selected = selected
        self.cell = QSize(300, 92)

    def sizeHint(self, option, index):
        return QSize(200, 92)

    def paint(self, painter, option, index):
        row = index.data(Qt.ItemDataRole.UserRole)
        if not row:
            return
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        selected = self.selected(row)
        painter.setPen(QPen(QColor('#4db2ff' if selected else '#2b3b49'), 2 if selected else 1))
        painter.setBrush(QColor('#22303b'))
        painter.drawRoundedRect(rect, 10, 10)
        art = QRectF(rect.left()+8, rect.top()+8, 64, 64)
        kind = row.get('kind')
        if kind == 'color':
            painter.setBrush(QColor(row.get('color') or '#6f9c9a'))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(art.adjusted(9, 9, -9, -9))
        else:
            collection = row.get('collection', '')
            model = row['name'] if kind == 'model' else ''
            backdrop = row['name'] if kind == 'backdrop' else ''
            symbol = row['name'] if kind == 'symbol' else ''
            if kind == 'theme' and row.get('members'):
                collection, model = row['members'][0]
            key = self.renderer.paint(painter, art, collection, model, backdrop, symbol)
            self.parent().watch(key, index)
        left = art.right()+12
        width = max(20, rect.right()-left-10)
        painter.setPen(QColor('#edf2f7'))
        painter.setFont(font(14, QFont.Weight.DemiBold))
        painter.drawText(QRectF(left, rect.top()+10, width, 38), Qt.TextFlag.TextWordWrap, row['name'])
        painter.setPen(QColor('#9badbb'))
        painter.setFont(font(12))
        painter.drawText(QRectF(left, rect.top()+51, width, 29), Qt.TextFlag.TextWordWrap, row.get('subtitle', ''))
        painter.restore()


class MobileOfferDelegate(QStyledItemDelegate):
    def __init__(self, window):
        super().__init__(window.view)
        self.window_ref = window
        self.text_cache = {}

    def sizeHint(self, option, index):
        return QSize(200, 148)

    def paint(self, painter, option, index):
        offer = index.data(Qt.ItemDataRole.UserRole)
        if not offer:
            return
        window = self.window_ref
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.setPen(QPen(QColor('#324453'), 1))
        painter.setBrush(QColor('#212d37'))
        painter.drawRoundedRect(rect, 10, 10)
        art = QRectF(rect.left()+8, rect.top()+10, 92, 92)
        key = window.renderer.paint(painter, art, offer.collection, offer.model, offer.backdrop, offer.symbol, offer.image)
        window.view.watch(key, index)
        if offer.key in window.store.data['favorites']:
            painter.setFont(font(19)); painter.setPen(QColor('#ffd693'))
            painter.drawText(art, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, '★')
        left = art.right()+10
        width = max(20, rect.right()-left-8)
        painter.setPen(QColor('#edf2f7')); painter.setFont(font(14, QFont.Weight.DemiBold))
        painter.drawText(QRectF(left, rect.top()+8, width, 34), Qt.TextFlag.TextWordWrap, f'{offer.collection} #{offer.number}')
        painter.setFont(font(17, QFont.Weight.DemiBold))
        painter.drawText(QRectF(left, rect.top()+43, width, 26), window.ratebook.display(offer, window.currency.currentData()))
        painter.setPen(QColor('#a0b1bf')); painter.setFont(font(12))
        painter.drawText(QRectF(left, rect.top()+75, width, 33), Qt.TextFlag.TextWordWrap,
                         ' · '.join(value for value in (offer.model, offer.backdrop) if value))
        painter.setPen(QColor(MARKETS[offer.market][1])); painter.setFont(font(11))
        source = MARKETS[offer.market][0] + ' · ' + tr('direct' if offer.source == 'direct' else 'saved' if offer.source == 'local-cache' else 'index')
        painter.drawText(QRectF(rect.left()+10, rect.top()+114, rect.width()-20, 22),
                         Qt.TextFlag.TextWordWrap, source + ' · ' + age_text(offer.checked_at))
        painter.restore()


class MobileSearchSelector(SearchSelector):
    def filter_items(self, text):
        super().filter_items(text)
        for i in range(self.items.count()):
            self.items.item(i).setSizeHint(QSize(0, 48))

    def showPopup(self):
        super().showPopup()
        owner = self.window()
        bounds = QRect(owner.mapToGlobal(QPoint(0, 0)), owner.size()).adjusted(8, 48, -8, -8)
        self.items.setMinimumHeight(80)
        self.popup.setGeometry(bounds.x(), bounds.y(), max(200, bounds.width()), min(430, max(160, bounds.height())))


class MobileFilterDialog(FilterDialog):
    def __init__(self, window, query=None, extra=None):
        super().__init__(window, query, extra)
        self._old_layout = steal_layout(self)
        self.setMinimumSize(0, 0)
        self.setSizeGripEnabled(False)
        layout = QVBoxLayout(self); layout.setContentsMargins(10, 8, 10, 8); layout.setSpacing(8)
        header = QHBoxLayout(); header.addWidget(label('filters', 'brand'), 1)
        close = touch(button('', self.reject, 'quiet', 'close')); close.setFixedWidth(44); close.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); header.addWidget(close)
        layout.addLayout(header)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(); form = QVBoxLayout(content); form.setContentsMargins(0, 0, 0, 0); form.setSpacing(8)
        self.summary.setWordWrap(True); form.addWidget(self.summary)
        self.category_select = touch(QComboBox())
        for key, title in (('collections','collection'), ('models','model'), ('backdrops','backdrop'), ('symbols','symbol'), ('themes','themes'), ('colors','color')):
            self.category_select.addItem(tr(title), key)
        self.category_select.currentIndexChanged.connect(lambda _: self.change_tab(self.category_select.currentData()))
        form.addWidget(self.category_select); form.addWidget(touch(self.search))
        list_view(self.grid, MobileTileDelegate(self.renderer, self.grid, self.is_selected), 92)
        self.grid.setFixedHeight(276); form.addWidget(self.grid)
        self.advanced_toggle = touch(button(tr('price')+' · '+tr('number')+' · '+tr('market'), self.toggle_advanced, 'quiet', 'chevron'))
        self.advanced_toggle.setCheckable(True); form.addWidget(self.advanced_toggle)
        self.advanced = QWidget(); advanced = QVBoxLayout(self.advanced); advanced.setContentsMargins(0,0,0,0); advanced.setSpacing(8)
        markets = QGridLayout()
        for i, check in enumerate(self.market_checks.values()):
            touch(check); markets.addWidget(check, i//2, i%2)
        advanced.addLayout(markets)
        old_unit = self.unit; self.unit = MobileSearchSelector()
        for title, code in old_unit.entries: self.unit.addItem(title, code)
        self.unit.setCurrentIndex(old_unit.currentIndex())
        prices = QHBoxLayout(); prices.setSpacing(6)
        for widget in (self.minimum, self.maximum, self.unit):
            widget.setMaximumWidth(16777215); prices.addWidget(touch(widget), 1)
        advanced.addLayout(prices)
        self.number.setMaximumWidth(16777215); advanced.addWidget(touch(self.number)); form.addWidget(self.advanced); form.addStretch(1)
        self.advanced.setVisible(bool(self.minimum.text() or self.maximum.text() or self.number.text()))
        self.advanced_toggle.setChecked(not self.advanced.isHidden())
        scroll.setWidget(content); layout.addWidget(scroll, 1)
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.form_scroll = scroll
        self.error.setWordWrap(True); layout.addWidget(self.error)
        footer = QHBoxLayout()
        for title, callback, role in (('reset', self.reset, 'quiet'), ('cancel', self.reject, ''), ('apply', self.apply, 'primary')):
            footer.addWidget(touch(button(title, callback, role)), 1)
        layout.addLayout(footer)
        self.change_tab(self.category)

    def toggle_advanced(self):
        self.advanced.setVisible(self.advanced_toggle.isChecked())

    def change_tab(self, key):
        super().change_tab(key)
        if hasattr(self, 'category_select'):
            self.category_select.blockSignals(True)
            self.category_select.setCurrentIndex(self.category_select.findData(key))
            self.category_select.blockSignals(False)
            self.grid.setGridSize(QSize(max(1, self.grid.viewport().width()), 92))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'category_select'):
            self.grid.setGridSize(QSize(max(1, self.width()-22), 92))

    def retranslate(self):
        super().retranslate()
        for i, key in enumerate(('collection','model','backdrop','symbol','themes','color')):
            self.category_select.setItemText(i, tr(key))
        self.advanced_toggle.setText(tr('price')+' · '+tr('number')+' · '+tr('market'))


class MobileDetailsDialog(DetailsDialog):
    def __init__(self, window, offer):
        super().__init__(window, offer)
        traits = self.findChild(QWidget, 'traits')
        self._old_layout = steal_layout(self)
        self.setMinimumSize(0, 0); self.setSizeGripEnabled(False); self.preview_size = 224
        layout = QVBoxLayout(self); layout.setContentsMargins(10, 8, 10, 8)
        title = label(f'{offer.collection} #{offer.number}', 'brand', True)
        header = QHBoxLayout(); header.addWidget(title, 1)
        close = touch(button('', self.reject, 'quiet', 'close')); close.setFixedWidth(44); close.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); header.addWidget(close); layout.addLayout(header)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget(); contents = QVBoxLayout(body); contents.setContentsMargins(0, 0, 0, 0); contents.setSpacing(10)
        self.image.setMinimumHeight(224); contents.addWidget(self.image)
        if traits: contents.addWidget(traits)
        self.price.setWordWrap(True); contents.addWidget(self.price); contents.addWidget(self.native); contents.addWidget(self.source_label)
        contents.addWidget(label('price_note', 'tiny', True))
        url = safe_url(offer.link) or safe_url(offer.telegram_url)
        self.open_button = touch(button('open_offer', lambda: QDesktopServices.openUrl(QUrl(url)), 'primary', 'arrow'))
        self.open_button.setEnabled(bool(url)); contents.addWidget(self.open_button)
        contents.addWidget(touch(button('copy_link', lambda: QApplication.clipboard().setText(url))))
        contents.addWidget(touch(self.favorite)); contents.addStretch()
        scroll.setWidget(body); layout.addWidget(scroll, 1)
        QScroller.grabGesture(scroll.viewport(), QScroller.ScrollerGestureType.TouchGesture)
        self.redraw()


class MobileWindow(MainWindow):
    def __init__(self, offline=False):
        super().__init__(offline=offline)
        self.setMinimumSize(320, 400); self.resize(360, 800)
        self.setStyleSheet(self.styleSheet()+'''
QLineEdit, QComboBox { min-height: 28px; }
QLineEdit#search { min-height: 24px; padding: 8px 10px; }
QMenu::item { padding: 14px 20px; }
QComboBox QAbstractItemView::item { min-height: 44px; }
''')
        QApplication.instance().installEventFilter(self)

    def build_ui(self):
        super().build_ui()
        old = self.takeCentralWidget()
        root = QWidget(); outer = QVBoxLayout(root); outer.setContentsMargins(10, 8, 10, 8); outer.setSpacing(8)
        old.setParent(root); old.hide(); self._desktop_shell = old
        header = QHBoxLayout(); brand = label('GiftFinder', 'brand'); brand.setFixedWidth(100); header.addWidget(brand)
        header.addStretch(1)
        touch(self.language_button); self.language_button.setFixedWidth(124); self.language_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); header.addWidget(self.language_button)
        self.mobile_menu_button = touch(button('⋮', self.mobile_menu, 'quiet')); self.mobile_menu_button.setFont(font(24)); self.mobile_menu_button.setFixedWidth(44); self.mobile_menu_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed); self.mobile_menu_button.setAccessibleName(tr('actions'))
        header.addWidget(self.mobile_menu_button); outer.addLayout(header)
        outer.addWidget(touch(self.search_edit))
        search = QHBoxLayout()
        for widget in (self.filter_button, self.find_button, self.stop_button):
            widget.setMinimumWidth(0); search.addWidget(touch(widget), 1)
        self.filter_button.setObjectName('mobileFiltersButton'); self.filter_button.setAccessibleName('Filters')
        outer.addLayout(search)
        self.active_scroll = QScrollArea(); self.active_scroll.setWidgetResizable(True); self.active_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.active_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff); self.active_scroll.setWidget(self.active_widget)
        self.active_scroll.setMaximumHeight(90); self.active_scroll.hide(); outer.addWidget(self.active_scroll)
        self._old_tools = steal_layout(self.tools_widget)
        tools = QGridLayout(self.tools_widget); tools.setContentsMargins(0,0,0,0); tools.setSpacing(6)
        self.counter.setWordWrap(True); tools.addWidget(self.counter, 0, 0)
        tools.addWidget(touch(self.actions_button), 0, 1)
        tools.addWidget(touch(self.sort), 1, 0)
        old_currency = self.currency; self.currency = MobileSearchSelector()
        for title, code in old_currency.entries: self.currency.addItem(title, code)
        self.currency.setCurrentIndex(old_currency.currentIndex()); self.currency.currentIndexChanged.connect(self.currency_changed)
        tools.addWidget(touch(self.currency), 1, 1); tools.setColumnStretch(0, 3); tools.setColumnStretch(1, 2)
        outer.addWidget(self.tools_widget); outer.addWidget(self.progress_widget)
        self.notice.setWordWrap(True); self.notice.setMaximumHeight(96); outer.addWidget(self.notice)
        old_home = self.stack.widget(0); self.stack.removeWidget(old_home); old_home.setParent(old); old_home.hide()
        home = QWidget(); home_layout = QVBoxLayout(home); home_layout.setContentsMargins(0,0,0,0); home_layout.setSpacing(6)
        home_layout.addWidget(touch(self.theme_toggle))
        list_view(self.theme_grid, MobileTileDelegate(self.renderer, self.theme_grid), 92); home_layout.addWidget(self.theme_grid)
        home_layout.addWidget(self.catalog_note)
        list_view(self.home_grid, MobileTileDelegate(self.renderer, self.home_grid), 92); home_layout.addWidget(self.home_grid, 1)
        self.stack.insertWidget(0, home); self.stack.setCurrentIndex(0)
        list_view(self.view, MobileOfferDelegate(self), 148)
        self.empty_title.setWordWrap(True); outer.addWidget(self.stack, 1)
        navigation = QHBoxLayout()
        navigation.addWidget(touch(self.nav_catalog, 52), 1); navigation.addWidget(touch(self.nav_favorites, 52), 1)
        self.mobile_saved_button = touch(button('searches', self.saved_searches, 'nav'), 52); navigation.addWidget(self.mobile_saved_button, 1)
        outer.addLayout(navigation)
        self.setCentralWidget(root); self.update_theme_visibility()

    def update_language_button(self):
        super().update_language_button()
        self.language_button.setText(language_code().replace('_', '-').upper())

    def update_theme_height(self):
        self.theme_grid.setFixedHeight(188)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for name, height in (('home_grid',92), ('theme_grid',92), ('view',148)):
            view = getattr(self, name, None)
            if view: view.setGridSize(QSize(max(1, self.width()-22), height))
        if hasattr(self, 'active_scroll'): self.update_mobile_chips()
        for dialog in getattr(self, 'dialogs', []):
            if dialog.isVisible(): self.fit_dialog(dialog)

    def update_mobile_chips(self):
        visible = bool(self.filter_label.text()) and self.mode == 'search'
        self.active_scroll.setVisible(visible)
        if visible:
            height = self.active_row.heightForWidth(max(1, self.width()-28))
            self.active_widget.setMinimumHeight(height)
            self.active_scroll.setFixedHeight(min(90, height+4))

    def filter_summary(self):
        super().filter_summary()
        if hasattr(self, 'active_scroll'):
            for child in self.active_widget.findChildren(MotionButton): touch(child)
            self.update_mobile_chips()

    def render_offers(self, *args):
        super().render_offers(*args)
        if hasattr(self, 'active_scroll'): self.update_mobile_chips()

    def show_catalog(self):
        super().show_catalog()
        if hasattr(self, 'active_scroll'): self.active_scroll.hide()

    def open_filters(self, category='collections', query=None, extra=None):
        if isinstance(category, bool): category = 'collections'
        if self.filter_dialog and query is not None: self.filter_dialog.close()
        if self.filter_dialog:
            self.filter_dialog.change_tab(category); self.filter_dialog.show(); return
        draft = query if query is not None else replace(self.filter_query, text=self.search_edit.text().strip())
        dialog = MobileFilterDialog(self, draft, extra); self.filter_dialog = dialog
        dialog.applied.connect(self.apply_filters); dialog.finished.connect(lambda _: setattr(self, 'filter_dialog', None))
        dialog.change_tab(category); self.keep_dialog(dialog)
        if os.environ.get('GIFT_FINDER_ANDROID_SMOKE') == '1':
            print('GIFTFINDER_ANDROID_FILTERS_OPEN', flush=True)

    def fit_dialog(self, dialog):
        dialog.setMinimumSize(0, 0); dialog.setMaximumSize(16777215, 16777215)
        if dialog.layout(): dialog.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        dialog.setGeometry(QRect(self.mapToGlobal(QPoint(0,0)), self.size()))

    def keep_dialog(self, dialog):
        dialog.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        for grip in dialog.findChildren(QSizeGrip): grip.hide()
        for child in dialog.findChildren(MotionButton):
            fixed_width = child.minimumWidth() if child.minimumWidth() == child.maximumWidth() else None
            touch(child)
            if fixed_width:
                child.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.fit_dialog(dialog)
        super().keep_dialog(dialog)
        self.fit_dialog(dialog)

    def show_details(self, index):
        offer = index.data(Qt.ItemDataRole.UserRole)
        if offer and not any(isinstance(d, DetailsDialog) and d.offer.key == offer.key for d in self.dialogs):
            self.keep_dialog(MobileDetailsDialog(self, offer))

    def simple_dialog(self, title, text):
        dialog = QDialog(self); layout = QVBoxLayout(dialog); layout.setContentsMargins(10,8,10,8)
        heading = label(title, 'brand', True); layout.addWidget(heading)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body = label(text() if callable(text) else text, 'muted', True); body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        scroll.setWidget(body); layout.addWidget(scroll, 1); layout.addWidget(touch(button('cancel', dialog.reject)))
        dialog.retranslate = lambda: (refresh_tree(dialog), body.setText(text() if callable(text) else text))
        self.keep_dialog(dialog); return dialog

    def rates_info(self):
        dialog = self.simple_dialog('rate_title', lambda: self.rate_label.text()+'\n\n'+self.ratebook.details())
        dialog.is_rate_dialog = True
        dialog.layout().insertWidget(dialog.layout().count()-1, touch(button('refresh', self.refresh_rates)))
        credit = QLabel('<a href="https://www.exchangerate-api.com">'+tr('rate_credit')+'</a>')
        credit.setWordWrap(True); credit.setOpenExternalLinks(True)
        dialog.layout().insertWidget(dialog.layout().count()-1, credit)

    def language_menu(self):
        dialog = QDialog(self); layout = QVBoxLayout(dialog); layout.setContentsMargins(10,8,10,8)
        layout.addWidget(label('language', 'brand'))
        languages = QListWidget(); layout.addWidget(languages, 1)
        for code, title in [('system',tr('system_language'))]+list(LANGUAGES.items()):
            item = QListWidgetItem(flag_icon(code), title); item.setData(Qt.ItemDataRole.UserRole, code); item.setSizeHint(QSize(0,48)); languages.addItem(item)
        languages.itemClicked.connect(lambda item: (self.change_language(item.data(Qt.ItemDataRole.UserRole)), dialog.accept()))
        layout.addWidget(touch(button('cancel', dialog.reject))); self.keep_dialog(dialog)

    def mobile_menu(self):
        menu = QMenu(self)
        for title, callback in (('rates',self.rates_info), ('sources',self.sources_info), ('save_search',self.save_search), ('export',self.export_csv), ('refresh',self.start_search)):
            action = menu.addAction(tr(title)); action.triggered.connect(callback)
            if title == 'export': action.setEnabled(bool(self.offer_model.offers))
        menu.exec(self.mobile_menu_button.mapToGlobal(QPoint(0,self.mobile_menu_button.height())))
        menu.deleteLater()

    def export_csv(self):
        if not self.offer_model.offers: return
        path, _ = QFileDialog.getSaveFileName(self, tr('export'), 'GiftFinder.csv', 'CSV (*.csv)')
        if not path: return
        output = io.StringIO(newline=''); writer = csv.writer(output, delimiter=';'); code = self.currency.currentData()
        writer.writerow([tr(key) for key in ('collection','number','model','backdrop','symbol','market','native_price','native_currency','converted_price','converted_currency','source','source_time','link')])
        def cell(value):
            text = str(value if value is not None else '')
            return "'"+text if text.lstrip()[:1] in ('=','+','-','@') else text
        for offer in self.offer_model.offers:
            writer.writerow([cell(value) for value in (offer.collection,offer.number,offer.model,offer.backdrop,offer.symbol,MARKETS[offer.market][0],offer.amount,'GRAM' if offer.currency in ('GRAM','TON') else offer.currency,self.ratebook.convert(offer,code),code,offer.source,date_text(offer.checked_at),offer.link)])
        payload = output.getvalue().encode('utf-8-sig'); target = QFile(path)
        if not target.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Truncate):
            self.show_notice(target.errorString()); return
        written = target.write(payload); target.close()
        if written != len(payload): self.show_notice(target.errorString()); return
        self.status.setText(tr('csv_saved')); self.show_notice(tr('csv_saved'))

    def show_notice(self, text):
        translated = message(str(text)); self.notice.setText(translated); self.notice.setToolTip(translated); self.notice.setVisible(bool(translated))

    def handle_back(self):
        for selector in self.findChildren(SearchSelector):
            if selector.popup.isVisible(): selector.hidePopup(); return
        for dialog in reversed(self.dialogs):
            if dialog.isVisible(): dialog.reject(); return
        if self.mode != 'catalog': self.show_catalog(); return
        self.close()

    def eventFilter(self, obj, event):
        if self.isVisible() and event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Back, Qt.Key.Key_Escape):
            self.handle_back(); return True
        if event.type() == QEvent.Type.FocusIn and isinstance(obj, QWidget) and self.filter_dialog and isinstance(self.filter_dialog, MobileFilterDialog):
            dialog = self.filter_dialog
            scroll = dialog.form_scroll
            if scroll.widget().isAncestorOf(obj):
                QTimer.singleShot(200, lambda widget=obj, d=dialog: d.form_scroll.ensureWidgetVisible(widget, 10, 18) if self.filter_dialog is d else None)
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(event)
