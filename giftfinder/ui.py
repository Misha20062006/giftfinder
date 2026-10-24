from __future__ import annotations

import csv
from collections import OrderedDict
import io
import os
import threading
import time
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, QStandardPaths, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QDesktopServices, QIcon, QAction, QKeySequence, QStaticText, QTransform, QTextOption
from PySide6.QtWidgets import (QMainWindow, QFrame, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QListView, QListWidget, QListWidgetItem, QStackedWidget,
    QStyledItemDelegate, QStyle, QDialog, QSizeGrip, QFileDialog, QApplication, QMenu, QProgressBar)

from .core import MARKETS, SearchQuery, SearchResult, Store, number, fmt, age_label, norm, safe_url
from .catalogue import Catalog, query_from_dict
from .providers import SearchEngine
from .currency import RateBook, NAMES, SYMBOLS
from .previews import Assets, PreviewRenderer
from .views import CardView
from .design import STYLE as MODERN_STYLE, font, mix, icon, MotionStack, open_motion, native_frame
from .selectors import FilterDialog, DragHeader, TileModel, TileDelegate
from .ui_common import STYLE, label, button, Task, OfferModel, SourceChip, application
from .controls import SearchSelector, SortCombo, FilterFlow
from .i18n import tr, bind, refresh_tree, set_language, language_code, LANGUAGES, theme_name, age_text, format_number, message
from .icons import flag_icon


STYLE_V2 = ''

def date_text(value):
    from PySide6.QtCore import QLocale,QDateTime
    return QLocale().toString(QDateTime.fromSecsSinceEpoch(int(value)),QLocale.FormatType.ShortFormat) if value else tr('unknown_time')


class OfferDelegate(QStyledItemDelegate):
    def __init__(self,window):super().__init__(window);self.window_ref=window;self.text_cache=OrderedDict()
    def sizeHint(self,option,index):return QSize(220,386)
    def paint(self,p,option,index):
        o=index.data(Qt.ItemDataRole.UserRole)
        if not o:return
        w=self.window_ref;hover=w.view.hover_for(index);selected=bool(option.state&QStyle.StateFlag.State_Selected)
        p.save();p.setClipRect(option.rect,Qt.ClipOperation.IntersectClip);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r=QRectF(option.rect.x()+10,option.rect.y()+8,196,370)
        art=QRectF(r.left(),r.top(),r.width(),196)
        key=w.renderer.paint(p,art,o.collection,o.model,o.backdrop,o.symbol,o.image);w.view.watch(key,index)
        if selected or hover:
            p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor('#4db2ff' if selected else '#61788c'),1.5 if selected else hover));p.drawRoundedRect(art,12,12)
        if o.key in w.store.data['favorites']:
            p.setPen(QColor('#ffd693'));p.setFont(font(19));p.drawText(art.adjusted(0,7,-10,0),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignRight,'★')
        x=r.left();width=int(r.width());code=w.currency.currentData();rates=w.ratebook.data
        signature=(o.key,o.model,o.backdrop,o.amount,o.currency,o.source,o.stale,code,language_code(),rates.get('gram_usd'),rates.get('star_usd'),rates.get('fx',{}).get(code))
        if signature not in self.text_cache:
            source=MARKETS[o.market][0]+(' · '+tr('saved') if o.source=='local-cache' else ' · '+tr('index') if o.source!='direct' else '')
            rows=((f'{o.collection} #{o.number}',14,QFont.Weight.DemiBold,'#f2f5f9',36),
                  (' · '.join(v for v in (o.model,o.backdrop) if v),12,QFont.Weight.Normal,'#95a6b7',44),
                  (w.ratebook.display(o,code),19,QFont.Weight.DemiBold,'#eaf4fd',29),
                  (o.price_label if code!='ORIGINAL' else age_text(o.checked_at),12,QFont.Weight.Normal,'#8499ab',20),
                  (source,11,QFont.Weight.Normal,MARKETS[o.market][1],20))
            prepared=[];y=207
            for text,size,weight,color,height in rows:
                static=QStaticText(text);static.setTextFormat(Qt.TextFormat.PlainText);static.setTextWidth(width)
                option_text=QTextOption();option_text.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);static.setTextOption(option_text)
                while True:
                    f=font(size,weight);static.prepare(QTransform(),f)
                    if static.size().height()<=height or size<=10:break
                    size-=1
                prepared.append((static,f,color,y));y+=static.size().height()+6
            self.text_cache[signature]=prepared
            while len(self.text_cache)>2048:self.text_cache.popitem(last=False)
        else:self.text_cache.move_to_end(signature)
        for static,f,color,y in self.text_cache[signature]:
            p.setFont(f);p.setPen(QColor(color));p.drawStaticText(QPointF(x,r.top()+y),static)
        p.restore()


class DetailsDialog(QDialog):
    def __init__(self,window,offer):
        super().__init__(window,Qt.WindowType.Dialog|Qt.WindowType.WindowTitleHint|Qt.WindowType.WindowCloseButtonHint|Qt.WindowType.WindowMaximizeButtonHint)
        self.window_ref=window;self.offer=offer;self.preview_size=272
        self.setWindowTitle(offer.slug);self.resize(660,760);self.setMinimumSize(560,700);self.setSizeGripEnabled(True)
        layout=QVBoxLayout(self);layout.setContentsMargins(26,22,26,14);layout.setSpacing(14)
        layout.addWidget(DragHeader(self,f'{offer.collection} #{offer.number}',MARKETS[offer.market][0],close_button=False))
        self.image=QLabel();self.image.setAlignment(Qt.AlignmentFlag.AlignCenter);self.image.setMinimumHeight(272);layout.addWidget(self.image,1)
        traits=QFrame();traits.setObjectName('traits');trait_row=QHBoxLayout(traits);trait_row.setContentsMargins(15,12,15,12);trait_row.setSpacing(14)
        for title,value in (('model',offer.model),('backdrop',offer.backdrop),('symbol',offer.symbol)):
            column=QVBoxLayout();column.setSpacing(4);column.addWidget(label(title,'tiny'));column.addWidget(label(value or 'not_specified','',True));trait_row.addLayout(column,1)
        layout.addWidget(traits)
        self.price=label('','hero');layout.addWidget(self.price);self.native=label(offer.price_label,'muted');layout.addWidget(self.native)
        self.source_label=label('','tiny',True);layout.addWidget(self.source_label);layout.addWidget(label('price_note','tiny',True))
        actions=QHBoxLayout();url=safe_url(offer.link) or safe_url(offer.telegram_url)
        open_button=button('open_offer',lambda:QDesktopServices.openUrl(QUrl(url)),'primary','arrow');open_button.setEnabled(bool(url));actions.addWidget(open_button,1)
        actions.addWidget(button('copy_link',lambda:QApplication.clipboard().setText(url)));layout.addLayout(actions)
        bottom=QHBoxLayout();self.favorite=button('',self.toggle_favorite,'quiet','bookmark');bottom.addWidget(self.favorite);bottom.addStretch();bottom.addWidget(QSizeGrip(self));layout.addLayout(bottom)
        window.renderer.changed.connect(self.preview_changed);window.currency.currentIndexChanged.connect(self.redraw);self.redraw();self.favorite_text()
    def redraw(self,*_):
        w=self.window_ref;o=self.offer;self.image.setPixmap(w.renderer.pixmap(o.collection,o.model,o.backdrop,o.symbol,self.preview_size,o.image));self.price.setText(w.ratebook.display(o,w.currency.currentData()))
        self.native.setText(o.price_label);self.source_label.setText(tr('source_direct' if o.source=='direct' else 'source_cached' if o.source=='local-cache' else 'source_index')+' · '+date_text(o.checked_at))
    def retranslate(self):refresh_tree(self);self.redraw();self.favorite_text()
    def preview_changed(self,key):
        o=self.offer
        if key==self.window_ref.renderer.key(o.collection,o.model,o.backdrop,o.symbol,self.preview_size,self.preview_size,1.,o.image):self.redraw()
    def favorite_text(self):self.favorite.setText(tr('remove_favorite' if self.offer.key in self.window_ref.store.data['favorites'] else 'add_favorite'))
    def toggle_favorite(self):
        w=self.window_ref;w.store.toggle(self.offer);self.favorite_text();w.view.viewport().update()
        if w.mode=='favorites':w.show_favorites()


class MainWindow(QMainWindow):
    def __init__(self, offline=False):
        super().__init__()
        self.offline = offline
        self.data_dir = Path(os.environ.get('GIFT_FINDER_DATA_DIR') or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        self.store = Store(self.data_dir)
        set_language(self.store.data['settings'].get('language','system'))
        self.catalog = Catalog(self.data_dir)
        self.engine = SearchEngine(self.catalog)
        self.ratebook = RateBook(self.data_dir)
        self.assets = Assets(self.data_dir,self)
        self.assets.offline = offline
        self.renderer = PreviewRenderer(self.catalog,self.assets)
        self.pool = QThreadPool(self); self.tasks = []
        self.cancelled = threading.Event(); self.generation = 0; self.busy = False; self.closing = False
        self.result = SearchResult(); self.offers = []; self.mode = 'catalog'; self.dialogs = []; self.filter_dialog = None
        settings = self.store.data['settings']
        try: self.filter_query = query_from_dict(settings.get('last_filter',{}))
        except (ValueError,TypeError): self.filter_query = SearchQuery()
        self.filter_extra = dict(settings.get('last_filter_extra',{}))
        self.setWindowTitle('GiftFinder'); self.resize(1400,900); self.setMinimumSize(1050,740)
        self.setWindowIcon(QIcon(str(Path(__file__).parent/'icon.png')))
        self.setStyleSheet(MODERN_STYLE)
        self.build_ui(); self.populate_catalog(); self.filter_summary(); self.update_rates_text()
        self.add_shortcut('Ctrl+F', self.search_edit.setFocus)
        self.add_shortcut('F5', self.start_search)
        if not offline:
            if any((self.filter_query.collection,self.filter_query.theme,self.filter_query.models,self.filter_query.targets,self.filter_query.text,self.filter_query.monochrome,self.filter_query.mono_colors)):
                QTimer.singleShot(0,self.start_search)
            QTimer.singleShot(100,self.refresh_rates)
            QTimer.singleShot(450,self.refresh_catalog)

    def add_shortcut(self, sequence, fn):
        action = QAction(self); action.setShortcut(QKeySequence(sequence)); action.triggered.connect(fn); self.addAction(action)

    def task(self, fn, done, fail=None, progress=None, updated=None):
        runner = Task(lambda emit,publish: fn(emit,publish) if updated else fn(emit))
        self.tasks.append(runner)
        def finish(value, failed=False):
            if runner in self.tasks: self.tasks.remove(runner)
            if self.closing: return
            (fail or self.show_notice)(value) if failed else done(value)
        runner.signals.done.connect(lambda value: finish(value))
        runner.signals.failed.connect(lambda value: finish(value,True))
        if progress: runner.signals.progress.connect(progress)
        if updated: runner.signals.updated.connect(updated)
        self.pool.start(runner)

    def build_ui(self):
        root=QWidget();self.setCentralWidget(root);outer=QVBoxLayout(root);outer.setContentsMargins(0,0,0,0);outer.setSpacing(0)
        header=QFrame();header.setObjectName('topbar');bar=QHBoxLayout(header);bar.setContentsMargins(30,0,30,0);bar.setSpacing(16)
        bar.addWidget(label('GiftFinder','brand'));bar.addSpacing(25)
        self.nav_catalog=button('catalog',self.show_catalog,'nav');self.nav_catalog.setCheckable(True);self.nav_catalog.setChecked(True)
        self.nav_favorites=button('favorites',self.show_favorites,'nav');self.nav_favorites.setCheckable(True)
        for b in (self.nav_catalog,self.nav_favorites):b.setMinimumHeight(54);bar.addWidget(b)
        saved=button('searches',self.saved_searches,'nav');saved.setMinimumHeight(54);bar.addWidget(saved);bar.addStretch()
        bar.addWidget(button('rates',self.rates_info,'quiet'))
        self.language_button=button('',self.language_menu,'select');bar.addWidget(self.language_button);outer.addWidget(header)
        body=QWidget();outer.addWidget(body,1);layout=QVBoxLayout(body);layout.setContentsMargins(30,22,30,18);layout.setSpacing(14)
        self.page_intro=QWidget(root);self.page_intro.hide()
        search=QHBoxLayout();search.setSpacing(10);self.search_edit=QLineEdit(self.filter_query.text);self.search_edit.setObjectName('search')
        bind(self.search_edit,'search_placeholder','setPlaceholderText');self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self.start_search);search.addWidget(self.search_edit,1)
        self.filter_button=button('filters',self.open_filters,'','filter');search.addWidget(self.filter_button)
        self.find_button=button('search',self.start_search,'primary');self.find_button.setMinimumWidth(96);search.addWidget(self.find_button)
        self.stop_button=button('stop',self.stop_search);self.stop_button.hide();search.addWidget(self.stop_button);layout.addLayout(search)
        self.active_widget=QWidget();self.active_row=FilterFlow(self.active_widget)
        self.filter_label=label('','muted');self.filter_label.hide();layout.addWidget(self.active_widget);self.active_widget.hide()
        self.tools_widget=QWidget();tools=QHBoxLayout(self.tools_widget);tools.setContentsMargins(8,0,8,0);tools.setSpacing(12)
        self.counter=label('','muted');tools.addWidget(self.counter,1)
        self.sort=SortCombo()
        self.sort_keys=[('sort_low','price_asc'),('sort_high','price_desc'),('sort_number','number'),('sort_fresh','fresh'),('sort_rarity','rarity')]
        for title,key in self.sort_keys:self.sort.addItem(tr(title),key)
        self.sort.setCurrentIndex(max(0,self.sort.findData(self.filter_query.sort_mode)));self.sort.currentIndexChanged.connect(self.render_offers);tools.addWidget(self.sort)
        self.currency=SearchSelector();self.currency.addItem(tr('original'),'ORIGINAL');self.currency.addItem('GRAM','GRAM');self.currency.addItem('Stars','Stars')
        for code in ['RUB','USD','EUR']+[c for c in self.ratebook.currencies() if c not in ('RUB','USD','EUR')]:self.currency.addItem(code+' · '+NAMES.get(code,code),code)
        self.currency.setCurrentIndex(max(0,self.currency.findData(self.store.data['settings'].get('display_currency','RUB'))));self.currency.setMaximumWidth(230)
        self.currency.currentIndexChanged.connect(self.currency_changed);tools.addWidget(self.currency)
        self.actions_button=button('actions',self.actions_menu,'quiet','chevron');tools.addWidget(self.actions_button)
        self.export_button=button('export',self.export_csv);self.export_button.hide()
        layout.addWidget(self.tools_widget);self.tools_widget.hide()
        self.progress_widget=QWidget();loading=QVBoxLayout(self.progress_widget);loading.setContentsMargins(8,0,8,0);loading.setSpacing(5)
        self.progress_label=label('','tiny',True);loading.addWidget(self.progress_label)
        self.progress_bar=QProgressBar();self.progress_bar.setTextVisible(False);self.progress_bar.setFixedHeight(3)
        self.progress_bar.setStyleSheet('QProgressBar{border:0;background:#2b3741;border-radius:1px;}QProgressBar::chunk{background:#58b7ff;border-radius:1px;}')
        loading.addWidget(self.progress_bar);layout.addWidget(self.progress_widget);self.progress_widget.hide()
        self.rate_widget=QWidget(root);self.rate_widget.hide();self.rate_label=label('');self.rate_label.hide()
        self.rate_button=button('refresh',self.refresh_rates);self.rate_button.hide()
        self.notice=label('','compactNotice');self.notice.setMaximumHeight(28);self.notice.hide();layout.addWidget(self.notice)
        self.sources_widget=QWidget(root);self.sources_widget.hide();source_layout=QHBoxLayout(self.sources_widget);source_layout.setContentsMargins(0,0,0,0);source_layout.setSpacing(8)
        self.source_chips={}
        for key in MARKETS:
            chip=SourceChip(key);self.source_chips[key]=chip;source_layout.addWidget(chip,1)
        self.stack=MotionStack();layout.addWidget(self.stack,1)
        home=QWidget();home_layout=QVBoxLayout(home);home_layout.setContentsMargins(0,0,0,0);home_layout.setSpacing(14)
        theme_title=QHBoxLayout();self.theme_toggle=button('',self.toggle_themes,'quiet','chevron');theme_title.addWidget(self.theme_toggle);theme_title.addStretch()
        theme_title.addWidget(button('all_themes',lambda:self.open_filters('themes'),'quiet','arrow'));home_layout.addLayout(theme_title)
        self.theme_grid=CardView(self.renderer,cell=QSize(220,100));self.theme_grid.setWrapping(True);self.theme_grid.setFlow(QListView.Flow.LeftToRight)
        self.theme_grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.theme_grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.theme_model=TileModel();self.theme_grid.setModel(self.theme_model);self.theme_grid.setItemDelegate(TileDelegate(self.renderer,parent=self.theme_grid,cell=QSize(220,100),ribbon=True))
        self.theme_grid.clicked.connect(lambda index:self.search_theme(index.data(Qt.ItemDataRole.UserRole)['key']));home_layout.addWidget(self.theme_grid)
        rule=QFrame();rule.setFixedHeight(1);rule.setStyleSheet('background:#2b3741;');home_layout.addWidget(rule)
        self.catalog_note=label('','muted');home_layout.addWidget(self.catalog_note)
        self.home_grid=CardView(self.renderer,cell=QSize(188,266));self.home_model=TileModel();self.home_grid.setModel(self.home_model)
        self.home_grid.setItemDelegate(TileDelegate(self.renderer,parent=self.home_grid,cell=QSize(188,266)));self.home_grid.clicked.connect(self.choose_collection);home_layout.addWidget(self.home_grid,1);self.stack.addWidget(home)
        self.view=CardView(self.renderer,cell=QSize(220,386));self.offer_model=OfferModel();self.view.setModel(self.offer_model);self.view.setItemDelegate(OfferDelegate(self))
        self.view.clicked.connect(self.show_details);self.view.activated.connect(self.show_details);self.stack.addWidget(self.view)
        empty=QWidget();empty_layout=QVBoxLayout(empty);empty_layout.addStretch();self.empty_title=label('no_results','emptyTitle');self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter);empty_layout.addWidget(self.empty_title)
        self.empty_note=label('','muted',True);self.empty_note.setAlignment(Qt.AlignmentFlag.AlignCenter);empty_layout.addWidget(self.empty_note);empty_layout.addStretch();self.stack.addWidget(empty)
        self.status=label('','tiny');self.status.hide()
        self.themes_collapsed=bool(self.store.data['settings'].get('themes_collapsed',False));self.update_theme_visibility()
        self.update_language_button()

    def update_theme_visibility(self):
        self.theme_grid.setVisible(not self.themes_collapsed)
        self.theme_toggle.setText(tr('themes') if self.themes_collapsed else tr('collapse_themes'))
        self.theme_toggle.glyph='chevron' if self.themes_collapsed else 'collapse'
        self.update_theme_height()

    def update_theme_height(self):
        columns=max(1,(self.width()-60)//220)
        rows=(self.theme_model.rowCount()+columns-1)//columns
        self.theme_grid.setFixedHeight(rows*100+4)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'theme_model'):self.update_theme_height()

    def toggle_themes(self):
        self.themes_collapsed=not self.themes_collapsed
        self.store.data['settings']['themes_collapsed']=self.themes_collapsed;self.store.save();self.update_theme_visibility()

    def update_language_button(self):
        self.language_button.badge=flag_icon('system' if self.store.data['settings'].get('language','system')=='system' else language_code())
        self.language_button.setText(LANGUAGES[language_code()]);self.language_button.setToolTip(tr('system_language') if self.store.data['settings'].get('language','system')=='system' else tr('language'))

    def language_menu(self):
        menu=QMenu(self);selected=self.store.data['settings'].get('language','system')
        for code,title in [('system',tr('system_language'))]+list(LANGUAGES.items()):
            action=menu.addAction(flag_icon(code),title+('  ✓' if code==selected else ''));action.setCheckable(True);action.setChecked(code==selected)
            action.triggered.connect(lambda checked=False,c=code:self.change_language(c))
            if code=='system':menu.addSeparator()
        menu.exec(self.language_button.mapToGlobal(self.language_button.rect().bottomLeft()));menu.deleteLater()

    def change_language(self,code):
        self.store.data['settings']['language']=code;self.store.save();set_language(code)
        refresh_tree(self);self.update_language_button();self.populate_catalog();self.filter_summary();self.update_theme_visibility()
        self.sort.blockSignals(True)
        for i,(key,_) in enumerate(self.sort_keys):self.sort.setItemText(i,tr(key))
        self.sort.blockSignals(False);self.currency.retranslate();self.update_rates_text();self.view.itemDelegate().text_cache.clear()
        self.render_offers()
        if self.progress_widget.isVisible():self.update_progress(self.result.progress)
        for dialog in list(self.dialogs):
            if hasattr(dialog,'retranslate'):dialog.retranslate()
        self.home_grid.viewport().update();self.theme_grid.viewport().update();self.view.viewport().update()

    def actions_menu(self):
        menu=QMenu(self)
        for title,callback in (('save_search',self.save_search),('export',self.export_csv),('sources',self.sources_info)):
            action=menu.addAction(tr(title));action.triggered.connect(callback)
            if title=='export':action.setEnabled(bool(self.offer_model.offers))
        menu.exec(self.actions_button.mapToGlobal(self.actions_button.rect().bottomLeft()));menu.deleteLater()

    def sources_info(self):
        def contents():
            rows=[]
            for key,(name,_) in MARKETS.items():
                matching=[s for s in self.result.statuses if s.market==key]
                rows.append(name+'\n'+('\n'.join(f'{s.source} · {date_text(s.checked_at)} · {message(s.note)}' for s in matching) or tr('no_fresh_source')))
            return '\n\n'.join(rows)
        self.simple_dialog('source_status',contents)

    def populate_catalog(self):
        rows = [{'kind':'collection','name':c,'collection':c,'key':c,'subtitle':tr('models_count',count=len(self.catalog.data.get('traits',{}).get(c,{}).get('models',[])))} for c in self.catalog.data['collections']]
        self.home_model.replace(rows)
        self.catalog_note.setText(tr('collections_count',count=len(rows)))
        self.theme_model.replace([{**row,'name':theme_name(k),'kind':'theme','key':k} for k,row in self.catalog.themes.items()])
        self.update_theme_height()

    def refresh_catalog(self):
        self.task(lambda emit:self.catalog.refresh(emit), self.catalog_ready)

    def catalog_ready(self,_):
        self.populate_catalog()
        if self.filter_dialog: self.filter_dialog.populate()

    def refresh_rates(self):
        if not self.rate_button.isEnabled(): return
        self.rate_button.setEnabled(False)
        for dialog in self.dialogs:
            if getattr(dialog,'is_rate_dialog',False):dialog.retranslate()
        self.task(lambda emit:self.ratebook.refresh(), self.rates_ready, self.rates_failed)

    def rates_failed(self,message):
        self.rate_button.setEnabled(True); self.show_notice(message); self.update_rates_text()
        for dialog in self.dialogs:
            if getattr(dialog,'is_rate_dialog',False):dialog.retranslate()

    def rates_ready(self,_):
        self.rate_button.setEnabled(True); self.update_rates_text(); self.render_offers()
        for dialog in self.dialogs:
            if isinstance(dialog,DetailsDialog): dialog.redraw()
            if getattr(dialog,'is_rate_dialog',False):dialog.retranslate()
        if self.ratebook.error: self.rate_label.setToolTip(self.ratebook.error)

    def update_rates_text(self):
        code = self.currency.currentData(); d = self.ratebook.data
        if code in ('GRAM','Stars','ORIGINAL'):code='USD'
        rate = number(d.get('fx',{}).get(code))
        gram,star = number(d.get('gram_usd')),number(d.get('star_usd'))
        parts = []
        if rate:
            unit = SYMBOLS.get(code,code)
            if gram: parts.append('1 GRAM ≈ '+format_number(gram*rate)+' '+unit)
            if star: parts.append('1 Star ≈ '+format_number(star*rate,4)+' '+unit)
        self.rate_label.setText(' · '.join(parts+[self.ratebook.note()]))
        self.rate_label.setToolTip(self.ratebook.details())

    def currency_changed(self,*_):
        self.store.data['settings']['display_currency'] = self.currency.currentData(); self.store.save()
        self.update_rates_text(); self.render_offers()
        for dialog in self.dialogs:
            if getattr(dialog,'is_rate_dialog',False):dialog.retranslate()

    def rates_info(self):
        details=lambda:self.rate_label.text()+'\n\n'+self.ratebook.details()
        dialog = self.simple_dialog(tr('rate_title'),details())
        credit = QLabel('<a style="color:#9acaff" href="https://www.exchangerate-api.com">'+tr('rate_credit')+'</a>')
        credit.setTextFormat(Qt.TextFormat.RichText); credit.setOpenExternalLinks(True)
        dialog.layout().insertWidget(2,credit)
        dialog.resize(650,390)
        dialog.is_rate_dialog=True
        refresh=button('refresh',self.refresh_rates,'quiet','refresh');refresh.setEnabled(self.rate_button.isEnabled());dialog.layout().insertWidget(dialog.layout().count()-1,refresh)
        def retranslate():
            refresh_tree(dialog);refresh.setEnabled(self.rate_button.isEnabled())
            dialog.setWindowTitle(tr('rate_title'));dialog.layout().itemAt(0).widget().findChildren(QLabel)[0].setText(tr('rate_title'))
            dialog.layout().itemAt(1).widget().setText(details());credit.setText('<a style="color:#9acaff" href="https://www.exchangerate-api.com">'+tr('rate_credit')+'</a>')
        dialog.retranslate=retranslate

    def simple_dialog(self,title,text):
        dialog = QDialog(self,Qt.WindowType.Dialog|Qt.WindowType.WindowTitleHint|Qt.WindowType.WindowCloseButtonHint|Qt.WindowType.WindowMaximizeButtonHint);dialog.setWindowTitle(tr(title))
        dialog.setSizeGripEnabled(True); layout = QVBoxLayout(dialog); layout.setContentsMargins(24,20,24,12)
        layout.addWidget(DragHeader(dialog,title,close_button=False)); body = label(text() if callable(text) else text,'muted',True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(body,1)
        layout.addWidget(QSizeGrip(dialog),0,Qt.AlignmentFlag.AlignRight)
        dialog.retranslate=lambda:(dialog.setWindowTitle(tr(title)),refresh_tree(dialog),body.setText(text() if callable(text) else text))
        self.keep_dialog(dialog); return dialog

    def keep_dialog(self,dialog):
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose,True)
        self.dialogs.append(dialog); dialog.finished.connect(lambda _:self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show();open_motion(dialog)

    def open_filters(self,category='collections',query=None,extra=None):
        if isinstance(category,bool): category = 'collections'
        if self.filter_dialog and query is not None:self.filter_dialog.close()
        if self.filter_dialog:
            self.filter_dialog.change_tab(category); self.filter_dialog.show(); return
        draft=query if query is not None else replace(self.filter_query,text=self.search_edit.text().strip())
        dialog = FilterDialog(self,draft,extra); self.filter_dialog = dialog
        dialog.applied.connect(self.apply_filters); dialog.finished.connect(lambda _:setattr(self,'filter_dialog',None))
        dialog.change_tab(category); self.keep_dialog(dialog)

    def apply_filters(self,query,extra):
        self.filter_query = query; self.filter_extra = extra;self.search_edit.setText(query.text); self.filter_summary(); self.start_search()

    def filter_summary(self):
        q = self.filter_query; parts=[];chips=[]
        if q.collection:chips.append((q.collection,'collection'))
        if q.theme in self.catalog.themes:chips.append((theme_name(q.theme),'theme'))
        if q.monochrome or q.mono_colors:chips.append((tr('theme_monochrome'),'monochrome'))
        if q.mono_colors:chips.append((', '.join(tr('color_'+color) for color in q.mono_colors),'mono_colors'))
        if q.targets:chips.append((q.targets[0][1] if len(q.targets)==1 else tr('selected_models',count=len(q.targets)),'targets'))
        elif q.models:chips.append((', '.join(q.models),'models'))
        if q.backdrops:chips.append((', '.join(q.backdrops),'backdrops'))
        if q.symbols:chips.append((', '.join(q.symbols),'symbols'))
        if q.number:chips.append(('#'+str(q.number),'number'))
        if self.filter_extra.get('min') or self.filter_extra.get('max'):
            chips.append((f'{self.filter_extra.get("min") or "0"}–{self.filter_extra.get("max") or "∞"} {self.filter_extra.get("unit","GRAM")}', 'price'))
        parts=[text for text,_ in chips]
        self.filter_label.setText(' · '.join(parts)); self.filter_label.setToolTip(self.filter_label.text())
        count = sum(bool(x) for x in (q.collection,q.theme,q.monochrome or q.mono_colors,q.mono_colors,q.targets or q.models,q.backdrops,q.symbols,q.number,self.filter_extra.get('min') or self.filter_extra.get('max')))
        self.filter_button.setText(tr('filters')+(f' · {count}' if count else ''))
        while self.active_row.count():
            item=self.active_row.takeAt(0)
            if item.widget():item.widget().deleteLater()
        for text,key in chips:
            b=button(text,lambda checked=False,k=key:self.remove_filter(k),'chip','close');b.setToolTip(text);self.active_row.addWidget(b)
        if chips:self.active_row.addWidget(button('reset',self.reset_filters,'quiet'))
        self.active_row.addStretch();self.active_widget.setVisible(bool(chips) and self.mode!='catalog')

    def remove_filter(self,key):
        if key=='price':self.filter_extra={**self.filter_extra,'min':'','max':''}
        elif key=='monochrome':self.filter_query=replace(self.filter_query,monochrome=False,mono_colors=())
        else:self.filter_query=replace(self.filter_query,**{key:None if key=='number' else '' if key in ('collection','theme') else ()})
        self.filter_summary()
        q=self.current_query()
        if any((q.collection,q.models,q.targets,q.theme,q.text,q.monochrome,q.mono_colors)):self.start_search()
        else:self.reset_filters()

    def reset_filters(self):
        self.stop_search(); self.filter_query = SearchQuery(); self.filter_extra = {}; self.search_edit.clear(); self.filter_summary(); self.show_catalog()

    def choose_collection(self,index):
        row = index.data(Qt.ItemDataRole.UserRole)
        self.open_filters('models',SearchQuery(collection=row['name']))

    def search_theme(self,key):
        if key=='monochrome':self.open_filters('colors',SearchQuery(monochrome=True),{});return
        self.filter_query = SearchQuery(theme=key)
        self.search_edit.clear(); self.filter_extra = {}; self.filter_summary(); self.start_search()

    def current_query(self):
        return replace(self.filter_query,text=self.search_edit.text().strip(),sort_mode=self.sort.currentData())

    def start_search(self):
        query = self.current_query()
        try: cached = self.engine.cached(query)
        except ValueError as error: self.show_notice(str(error)); return
        self.cancelled.set(); self.cancelled = threading.Event(); cancelled = self.cancelled
        self.generation += 1; generation = self.generation
        self.tools_widget.show();self.nav_catalog.setChecked(False);self.nav_favorites.setChecked(False)
        self.mode = 'search'; self.busy = True; self.stop_button.show(); self.notice.hide()
        self.filter_query = query; self.filter_summary(); self.result = cached; self.offers = cached.offers
        self.update_progress({'phase':'searching','checked':0,'total':0,'pages':0})
        settings = self.store.data['settings']; settings['last_filter'] = asdict(query); settings['last_filter_extra'] = self.filter_extra; self.store.save()
        self.render_offers(); self.status.setText(tr('updating'))
        for chip in self.source_chips.values(): chip.update_status(cached.statuses,cached.offers)
        if self.offline:
            self.busy = False; self.stop_button.hide(); self.progress_widget.hide();self.render_offers(); return
        self.task(lambda emit,publish:self.engine.search(query,emit,cancelled,publish),
            lambda result:self.accept_result(result,generation,True),
            lambda message:self.search_failed(message,generation),
            lambda message:self.search_progress(message,generation),
            lambda result:self.accept_result(result,generation,False))

    def search_progress(self,message,generation):
        if generation == self.generation and self.mode == 'search': self.status.setText(message)

    def update_progress(self,data):
        if self.mode!='search':self.progress_widget.hide();return
        self.progress_widget.show();total=data.get('total',0);checked=data.get('checked',0)
        phase=data.get('phase','searching')
        self.progress_bar.setRange(0,total or (0 if phase=='searching' else 1));self.progress_bar.setValue(checked)
        caption=tr('progress_checked',checked=checked,total=total,offers=len(self.offers),pages=data.get('pages',0)) if total else tr('updating') if phase=='searching' else tr('offers_count',count=len(self.offers))
        if data.get('phase')=='stopped':caption=tr('stopped')+' · '+caption
        elif data.get('phase')=='complete':caption=tr('progress_complete')+' · '+caption
        if data.get('errors'):caption+=' · '+tr('source_partial')+': '+str(data['errors'])
        self.progress_label.setText(caption)
        self.progress_label.setToolTip(tr('progress_note'))
        if total:self.progress_bar.setToolTip(tr('progress_note'))

    def search_failed(self,message,generation):
        if generation != self.generation: return
        self.busy = False; self.stop_button.hide();self.progress_widget.hide(); self.show_notice(message); self.render_offers()

    def accept_result(self,result,generation,finished=False):
        if generation != self.generation: return
        self.result = result; self.offers = result.offers
        if finished: self.busy = False; self.stop_button.hide()
        if self.mode != 'search': return
        self.update_progress(result.progress)
        self.render_offers()
        for chip in self.source_chips.values(): chip.update_status(result.statuses,result.offers)
        warnings = list(result.warnings)
        if warnings: self.show_notice(' '.join(dict.fromkeys(warnings)))
        if finished:
            unavailable = {MARKETS[s.market][0] for s in result.statuses if s.state == 'unavailable'}
            self.status.setText(tr('offers_count',count=len(result.offers))+' · '+result.scope+(' · '+tr('source_unavailable')+': '+', '.join(sorted(unavailable)) if unavailable else ''))

    def stop_search(self):
        self.cancelled.set(); self.generation += 1; self.busy = False
        if hasattr(self,'stop_button'): self.stop_button.hide()
        if hasattr(self,'status'): self.status.setText(tr('stopped'))
        if hasattr(self,'progress_widget') and self.progress_widget.isVisible():self.update_progress({**self.result.progress,'phase':'stopped'})

    def render_offers(self,*_):
        if not hasattr(self,'view') or self.mode == 'catalog': return
        self.tools_widget.show();self.active_widget.setVisible(bool(self.filter_label.text()) and self.mode=='search')
        rows = list(self.offers); mode = self.sort.currentData()
        if self.mode == 'search':
            def bound(key):
                value = str(self.filter_extra.get(key,'')).strip().replace(',','.')
                return number(value)
            low,high = bound('min'),bound('max')
            unit = self.filter_extra.get('unit','GRAM')
            if low is not None or high is not None:
                def within(o):
                    value = self.ratebook.convert(o,'GRAM' if unit == 'TON' else unit)
                    return value is not None and (low is None or value >= low) and (high is None or value <= high)
                rows = [o for o in rows if within(o)]
        if mode in ('price_asc','price_desc'):
            rates=self.ratebook.data
            gram=number(rates.get('gram_usd'));stars=number(rates.get('star_usd'))
            factors={'TON':gram,'GRAM':gram,'Stars':stars}
            def key(o):
                factor=factors.get(o.currency)
                value = o.amount*factor if o.amount is not None and factor else None
                return (value is None, -value if value is not None and mode == 'price_desc' else value or Decimal(0),o.key)
            rows.sort(key=key)
        elif mode == 'number': rows.sort(key=lambda o:(o.number,o.collection,o.key))
        elif mode == 'fresh': rows.sort(key=lambda o:(o.stale,-(o.checked_at or 0),o.key))
        elif mode == 'rarity': rows.sort(key=lambda o:(o.rarity is None,o.rarity or Decimal(0),o.key))
        scroll = self.view.verticalScrollBar().value(); self.offer_model.replace(rows); self.view.verticalScrollBar().setValue(scroll)
        self.counter.setText((tr('favorites')+': '+str(len(rows)) if self.mode=='favorites' else tr('offers_count',count=len(rows)))+(' · '+tr('updating') if self.busy and self.mode=='search' else ''))
        self.export_button.setEnabled(bool(rows));self.sources_widget.hide()
        if rows: self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(2); self.empty_title.setText(tr('loading' if self.busy else 'no_results'))
            self.empty_note.setText(tr('live_results' if self.busy else 'change_filters' if self.mode=='search' else 'empty_favorites'))

    def show_catalog(self):
        self.stop_search(); self.mode = 'catalog'; self.stack.setCurrentIndex(0); self.sources_widget.hide(); self.notice.hide()
        self.active_widget.hide();self.tools_widget.hide();self.progress_widget.hide();self.nav_catalog.setChecked(True);self.nav_favorites.setChecked(False);self.status.setText('')

    def show_favorites(self):
        self.tools_widget.show();self.nav_catalog.setChecked(False);self.nav_favorites.setChecked(True)
        self.stop_search(); self.mode = 'favorites'; self.offers = self.store.favorites(); self.notice.hide(); self.render_offers()
        self.progress_widget.hide()
        self.status.setText(tr('saved'))

    def show_details(self,index):
        offer = index.data(Qt.ItemDataRole.UserRole)
        if offer:
            if any(isinstance(d,DetailsDialog) and d.offer.key==offer.key for d in self.dialogs):return
            self.keep_dialog(DetailsDialog(self,offer))

    def show_notice(self,message):
        from .i18n import message as translate_message
        message=translate_message(str(message));self.notice.setToolTip(message);self.notice.setText(self.notice.fontMetrics().elidedText(message.replace('\n',' '),Qt.TextElideMode.ElideRight,max(300,self.width()-80)));self.notice.setVisible(bool(message))

    def save_search(self):
        q = self.current_query()
        try: self.catalog.resolve(q)
        except ValueError as error: self.show_notice(str(error)); return
        payload = {**asdict(q),'extra':dict(self.filter_extra)}
        # JSON round-trip keeps tuple/list equality consistent with old profiles.
        import json
        payload = json.loads(json.dumps(payload))
        if payload not in self.store.data['searches']: self.store.data['searches'].append(payload); self.store.save()
        self.status.setText(tr('search_saved'));self.show_notice(tr('search_saved'))

    def saved_searches(self):
        dialog = QDialog(self,Qt.WindowType.Dialog|Qt.WindowType.WindowTitleHint|Qt.WindowType.WindowCloseButtonHint|Qt.WindowType.WindowMaximizeButtonHint);dialog.setWindowTitle(tr('saved_searches')); dialog.resize(680,480); dialog.setSizeGripEnabled(True)
        layout = QVBoxLayout(dialog); layout.setContentsMargins(24,20,24,12); layout.addWidget(DragHeader(dialog,'saved_searches',close_button=False))
        items = QListWidget();items.setWordWrap(True);items.setTextElideMode(Qt.TextElideMode.ElideNone); layout.addWidget(items,1)
        def populate():
            selected=items.currentRow();items.clear()
            for i,data in enumerate(self.store.data['searches']):
                q = query_from_dict(data)
                title = ' · '.join(x for x in (q.collection,theme_name(q.theme) if q.theme else '',tr('theme_monochrome') if q.monochrome else '',', '.join(tr('color_'+color) for color in q.mono_colors),q.text,', '.join(q.models),tr('selected_models',count=len(q.targets)) if q.targets else '',', '.join(q.backdrops)) if x) or tr('search')
                item = QListWidgetItem(title); item.setData(Qt.ItemDataRole.UserRole,i); items.addItem(item)
            if selected>=0:items.setCurrentRow(selected)
        populate()
        if not items.count(): layout.addWidget(label('no_searches','muted'))
        def load():
            item = items.currentItem()
            if not item: return
            data = self.store.data['searches'][item.data(Qt.ItemDataRole.UserRole)]
            self.filter_query = query_from_dict(data); self.filter_extra = data.get('extra',{'min':data.get('price_min',data.get('min','')),'max':data.get('price_max',data.get('max','')),'unit':data.get('price_currency',data.get('unit','GRAM'))})
            self.sort.setCurrentIndex(max(0,self.sort.findData(self.filter_query.sort_mode)))
            self.search_edit.setText(self.filter_query.text); self.filter_summary(); dialog.close(); self.start_search()
        items.itemDoubleClicked.connect(lambda _:load()); layout.addWidget(button('open_search',load,'primary')); layout.addWidget(QSizeGrip(dialog),0,Qt.AlignmentFlag.AlignRight)
        dialog.retranslate=lambda:(dialog.setWindowTitle(tr('saved_searches')),refresh_tree(dialog),populate())
        self.keep_dialog(dialog)

    def export_csv(self):
        if not self.offer_model.offers: return
        path,_ = QFileDialog.getSaveFileName(self,tr('export'),'GiftFinder.csv','CSV (*.csv)')
        if not path: return
        out = io.StringIO(newline=''); writer = csv.writer(out,delimiter=';'); code = self.currency.currentData()
        writer.writerow([tr(key) for key in ('collection','number','model','backdrop','symbol','market','native_price','native_currency','converted_price','converted_currency','source','source_time','link')])
        def cell(value):
            text = str(value if value is not None else '')
            return "'"+text if text.lstrip()[:1] in ('=','+','-','@') else text
        for o in self.offer_model.offers:
            writer.writerow([cell(v) for v in (o.collection,o.number,o.model,o.backdrop,o.symbol,MARKETS[o.market][0],o.amount,'GRAM' if o.currency in ('GRAM','TON') else o.currency,self.ratebook.convert(o,code),code,o.source,date_text(o.checked_at),o.link)])
        Path(path).write_text(out.getvalue(),encoding='utf-8-sig'); self.status.setText(tr('csv_saved'));self.show_notice(tr('csv_saved'))

    def showEvent(self,event):
        super().showEvent(event);native_frame(self)

    def closeEvent(self,event):
        self.closing = True; self.cancelled.set(); self.generation += 1
        for dialog in list(self.dialogs): dialog.close()
        super().closeEvent(event)
