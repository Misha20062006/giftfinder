"""Native searchable selectors; no editable display values or web content."""
from PySide6.QtCore import Qt, Signal, QEvent, QPoint, QSize, QRect
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QApplication, QComboBox, QLayout, QWidgetItem)
from PySide6.QtGui import QPainter, QColor, QPen
from .design import MotionButton, font, icon
from .i18n import tr, currency_name, language_code
from .icons import currency_icon


class FilterFlow(QLayout):
    """Wrap applied-filter buttons so every removal action stays reachable."""
    def __init__(self,parent):
        super().__init__(parent);self.entries=[];self.setContentsMargins(0,0,0,0);self.setSpacing(8)
    def addItem(self,item):self.entries.append(item)
    def addWidget(self,widget):self.addChildWidget(widget);self.addItem(QWidgetItem(widget))
    def addStretch(self,*args):pass
    def count(self):return len(self.entries)
    def itemAt(self,index):return self.entries[index] if 0<=index<len(self.entries) else None
    def takeAt(self,index):return self.entries.pop(index) if 0<=index<len(self.entries) else None
    def expandingDirections(self):return Qt.Orientation(0)
    def hasHeightForWidth(self):return True
    def heightForWidth(self,width):return self.arrange(QRect(0,0,width,0),True)
    def minimumSize(self):return QSize(min(160,max((i.minimumSize().width() for i in self.entries),default=0)),max((i.sizeHint().height() for i in self.entries),default=0))
    def sizeHint(self):return self.minimumSize()
    def setGeometry(self,rect):super().setGeometry(rect);self.arrange(rect,False)
    def arrange(self,rect,measure):
        space=self.spacing();rtl=self.parentWidget().layoutDirection()==Qt.LayoutDirection.RightToLeft
        left=rect.x();right=rect.x()+rect.width();x=right if rtl else left;y=rect.y();height=0
        for item in self.entries:
            hint=item.sizeHint();width=min(hint.width(),max(0,rect.width()));item_height=item.heightForWidth(width) if item.hasHeightForWidth() else hint.height()
            if height and ((x-width<left) if rtl else (x+width>right)):
                x=right if rtl else left;y+=height+space;height=0
            if not measure:item.setGeometry(QRect(x-width if rtl else x,y,width,item_height))
            x+=-(width+space) if rtl else width+space;height=max(height,item_height)
        return y+height-rect.y()


class SearchSelector(MotionButton):
    currentIndexChanged = Signal(int)
    def __init__(self, entries=(), parent=None):
        super().__init__('', self.showPopup, 'select')
        self.setParent(parent);self.entries=[];self.position=-1
        self.popup=QFrame(self,Qt.WindowType.Popup)
        self.popup.setObjectName('selectorPopup')
        layout=QVBoxLayout(self.popup);layout.setContentsMargins(10,10,10,10);layout.setSpacing(7)
        self.search=QLineEdit();self.search.setClearButtonEnabled(True);self.search.setPlaceholderText(tr('currency_search'))
        self.items=QListWidget();self.items.setObjectName('selectorItems');self.items.setMinimumHeight(260);self.items.setIconSize(QSize(28,28))
        self.items.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.items.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.items.setWordWrap(True);self.items.setTextElideMode(Qt.TextElideMode.ElideNone)
        layout.addWidget(self.search);layout.addWidget(self.items,1)
        self.search.textChanged.connect(self.filter_items);self.items.itemClicked.connect(self.choose)
        self.search.installEventFilter(self);self.items.installEventFilter(self)
        for title,code in entries:self.addItem(title,code)
    def sizeHint(self):
        hint=super().sizeHint();return QSize(max(120,hint.width()),max(38,hint.height()))
    def addItem(self,title,code=None):
        self.entries.append((title,code if code is not None else title))
        if self.position<0:self.setCurrentIndex(0)
    def count(self):return len(self.entries)
    def itemData(self,index):return self.entries[index][1] if 0<=index<len(self.entries) else None
    def itemText(self,index):return self.entries[index][0] if 0<=index<len(self.entries) else ''
    def findData(self,code):return next((i for i,(_,c) in enumerate(self.entries) if c==code),-1)
    def currentIndex(self):return self.position
    def currentData(self):return self.itemData(self.position)
    def currentText(self):return self.itemText(self.position)
    def setCurrentIndex(self,index):
        if not 0<=index<len(self.entries):return
        old=self.position;self.position=index;self.update_text()
        if old!=index:self.currentIndexChanged.emit(index)
    def update_text(self):
        code=self.currentData()
        self.badge=currency_icon(code)
        self.setText(tr('original') if code=='ORIGINAL' else str(code or ''))
        self.updateGeometry()
        self.setToolTip(currency_name(code))
    def retranslate(self):
        self.search.setPlaceholderText(tr('currency_search'));self.update_text()
        if self.popup.isVisible():self.filter_items(self.search.text())
    def filter_items(self,text):
        self.items.clear();term=text.strip().casefold()
        for i,(title,code) in enumerate(self.entries):
            name=tr('original') if code=='ORIGINAL' else currency_name(code)
            display=name if code in ('ORIGINAL','GRAM','Stars') else f'{code}  ·  {name}'
            haystack=' '.join((str(code),title,name,currency_name(code,'en'),currency_name(code,'ru'))).casefold()
            if term and term not in haystack:continue
            item=QListWidgetItem(currency_icon(code),display);item.setToolTip(display);item.setData(Qt.ItemDataRole.UserRole,i);self.items.addItem(item)
            if i==self.position:self.items.setCurrentItem(item)
        if self.items.count() and not self.items.currentItem():self.items.setCurrentRow(0)
    def choose(self,item):
        if item:self.setCurrentIndex(item.data(Qt.ItemDataRole.UserRole));self.hidePopup();self.setFocus()
    def showPopup(self):
        if not self.isEnabled():return
        self.popup.setLayoutDirection(self.layoutDirection())
        self.search.clear();self.filter_items('');self.popup.resize(max(340,min(460,self.width()+190)),365)
        point=self.mapToGlobal(QPoint(0,self.height()+5));screen=self.screen().availableGeometry()
        x=point.x() if self.layoutDirection()==Qt.LayoutDirection.RightToLeft else point.x()+self.width()-self.popup.width()
        y=point.y()
        if y+self.popup.height()>screen.bottom():y=self.mapToGlobal(QPoint(0,0)).y()-self.popup.height()-5
        self.popup.move(max(screen.left(),min(x,screen.right()-self.popup.width())),max(screen.top(),y))
        self.popup.show();self.search.setFocus()
    def hidePopup(self):self.popup.hide()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.KeyPress:
            key=event.key()
            if key==Qt.Key.Key_Escape:self.hidePopup();self.setFocus();return True
            if key in (Qt.Key.Key_Return,Qt.Key.Key_Enter):self.choose(self.items.currentItem());return True
            if obj is self.search and key in (Qt.Key.Key_Down,Qt.Key.Key_Up):
                step=1 if key==Qt.Key.Key_Down else -1
                self.items.setCurrentRow(max(0,min(self.items.count()-1,self.items.currentRow()+step)));return True
        return super().eventFilter(obj,event)
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Down,Qt.Key.Key_Space,Qt.Key.Key_Return):self.showPopup();event.accept()
        else:super().keyPressEvent(event)


class SortCombo(QComboBox):
    def __init__(self,parent=None):
        super().__init__(parent);self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    def paintEvent(self,event):
        super().paintEvent(event)
        from PySide6.QtCore import QRectF
        p=QPainter(self);x=10 if self.layoutDirection()==Qt.LayoutDirection.RightToLeft else self.width()-24
        icon(p,'chevron',QRectF(x,self.height()/2-8,16,16),'#a4b4c2')
