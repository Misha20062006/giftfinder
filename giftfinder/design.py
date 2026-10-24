"""Qt Widgets visual system. No HTML, QML or browser engine."""
import ctypes
import os
from functools import lru_cache

from PySide6.QtCore import Qt,QSize,QRectF,QPointF,Property,QPropertyAnimation,QEasingCurve,QParallelAnimationGroup
from PySide6.QtGui import QColor,QPainter,QPen,QFont,QPainterPath,QTextLayout,QTextOption
from PySide6.QtWidgets import QPushButton,QWidget,QStackedWidget,QApplication,QCheckBox,QStyle,QStyleOptionButton,QSizePolicy
from .i18n import EN, bind

BG='#1a2026';PANEL='#212a33';FIELD='#242e38';ACCENT='#4db2ff';PRIMARY='#248bda';TEXT='#f2f5f8';MUTED='#95a3b2'

STYLE='''
QWidget { background: #1a2026; color: #edf2f7; font-family: "Segoe UI"; font-size: 14px; }
QMainWindow { background: #1a2026; }
QLabel, DragHeader, QSizeGrip { background: transparent; }
QFrame#topbar { background: #1a2026; border: 0; border-bottom: 1px solid #2b3640; }
QLabel#brand { font-size: 20px; font-weight: 650; }
QLabel#hero { font-size: 32px; font-weight: 650; letter-spacing: -0.8px; }
QLabel#eyebrow { font-size: 11px; color: #63b8f5; font-weight: 600; letter-spacing: 1.5px; }
QLabel#emptyTitle { font-size: 24px; font-weight: 650; }
QLabel#counter { font-size: 18px; font-weight: 650; }
QLabel#sectionTitle { font-size: 16px; font-weight: 600; }
QLabel#windowTitle { font-size: 20px; font-weight: 650; }
QLabel#muted { color: #95a3b2; font-size: 13px; }
QLabel#tiny { color: #8b9aa9; font-size: 12px; }
QLabel#rate { color: #8fa1b2; font-size: 12px; }
QLabel#notice { color: #d4b581; background: #302c23; border: 1px solid #453d2e; border-radius: 8px; padding: 9px 13px; font-size: 12px; }
QDialog#floating { background: #1d252e; border: 1px solid #465766; border-radius: 14px; }
QLineEdit, QComboBox { color: #edf3f9; background: #242e38; border: 1px solid #34424f; border-radius: 8px; padding: 8px 12px; min-height: 22px; selection-background-color: #206ca6; }
QLineEdit:focus,QComboBox:focus { border-color: #4db2ff; background: #263340; }
QLineEdit#search { font-size: 15px; padding: 12px 15px; border: 1px solid #394956; border-radius: 10px; }
QComboBox::drop-down { border: 0; width: 24px; }
QComboBox QAbstractItemView { background: #283440; color: #edf3f9; border: 1px solid #425466; selection-background-color: #31516d; padding: 6px; outline: 0; }
QCheckBox { color: #bac8d5; spacing: 8px; padding: 4px 0; background: transparent; font-size: 13px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #586a7c; border-radius: 4px; background: #242e38; }
QCheckBox::indicator:checked { background: #248bda; border-color: #4db2ff; image: url(:/none); }
QCheckBox:checked { color: #e2f1ff; }
QListView,QListWidget { background: transparent; border: 0; outline: 0; }
QListWidget::item { padding: 14px 12px; border-bottom: 1px solid #34424f; }
QListWidget::item:selected { background: #2b4359; border-radius: 6px; }
QScrollBar:vertical { width: 8px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 6px; background: transparent; margin: 0; }
QScrollBar::handle:vertical,QScrollBar::handle:horizontal { background: #415363; border-radius: 3px; min-height: 30px; min-width: 30px; }
QScrollBar::add-line,QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page,QScrollBar::sub-page { background: transparent; }
QToolTip { color: #eef5fc; background: #2a3a49; border: 1px solid #4b6175; padding: 8px; }
QFrame#traits { background: #242f3b; border-radius: 10px; }
QFrame#selectorPopup { background:#222c35; border:1px solid #455562; border-radius:9px; }
QListWidget#selectorItems::item { padding:8px 9px; border:0; border-radius:4px; }
QListWidget#selectorItems::item:selected { background:#314b60; color:#f0f6fa; }
QComboBox::down-arrow { image:none; }
QMenu { background:#232e38; border:1px solid #455562; padding:6px; }
QMenu::item { padding:8px 24px; border-radius:4px; }
QMenu::item:selected { background:#314b60; }
QMenu::separator { height:1px; background:#3a4855; margin:5px; }
'''


@lru_cache(maxsize=64)
def font(px,weight=QFont.Weight.Normal):
    f=QFont('Segoe UI');f.setPixelSize(px);f.setWeight(weight);return f


@lru_cache(maxsize=1)
def motion_enabled():
    if os.environ.get('GIFT_FINDER_REDUCED_MOTION')=='1':return False
    if os.name=='nt':
        value=ctypes.c_int(1)
        try:
            if ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(value),0):return bool(value.value)
        except (OSError,AttributeError):pass
    return True


def native_frame(widget):
    if os.name!='nt' or QApplication.platformName()=='offscreen':return
    try:
        hwnd=ctypes.c_void_p(int(widget.winId()))
        for attribute,value in ((20,1),(33,2),(35,0x0026201a)):
            field=ctypes.c_int(value)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd,attribute,ctypes.byref(field),ctypes.sizeof(field))
    except (OSError,AttributeError):pass


def mix(a,b,t):
    a,b=QColor(a),QColor(b)
    return QColor(round(a.red()+(b.red()-a.red())*t),round(a.green()+(b.green()-a.green())*t),round(a.blue()+(b.blue()-a.blue())*t))


def icon(p,name,r,color=TEXT):
    p.save();p.translate(r.topLeft());p.scale(r.width()/24,r.height()/24)
    p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor(color),1.7,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin));p.setBrush(Qt.BrushStyle.NoBrush)
    if name=='search':p.drawEllipse(QRectF(4,4,12,12));p.drawLine(QPointF(14,14),QPointF(20,20))
    elif name=='filter':
        for y,x in ((6,9),(12,16),(18,7)):
            p.drawLine(4,y,20,y);p.setBrush(QColor(PANEL));p.drawEllipse(QPointF(x,y),2,2);p.setBrush(Qt.BrushStyle.NoBrush)
    elif name=='bookmark':
        path=QPainterPath();path.moveTo(6,4);path.lineTo(18,4);path.lineTo(18,21);path.lineTo(12,17);path.lineTo(6,21);path.closeSubpath();p.drawPath(path)
    elif name=='close':p.drawLine(6,6,18,18);p.drawLine(18,6,6,18)
    elif name=='refresh':p.drawArc(QRectF(4,4,16,16),30*16,290*16);p.drawLine(19,4,20,10);p.drawLine(20,10,14,9)
    elif name=='export':p.drawLine(12,3,12,16);p.drawLine(7,11,12,16);p.drawLine(17,11,12,16);p.drawPolyline([QPointF(4,15),QPointF(4,21),QPointF(20,21),QPointF(20,15)])
    elif name=='arrow':p.drawLine(5,12,19,12);p.drawLine(14,7,19,12);p.drawLine(14,17,19,12)
    elif name=='grid':
        for x in (4,14):
            for y in (4,14):p.drawRoundedRect(QRectF(x,y,6,6),1.5,1.5)
    elif name=='gift':
        p.drawRoundedRect(QRectF(4,10,16,11),2,2);p.drawRoundedRect(QRectF(3,7,18,5),1.5,1.5);p.drawLine(12,7,12,21)
        p.drawEllipse(QRectF(6,2,6,5));p.drawEllipse(QRectF(12,2,6,5))
    elif name=='chevron':p.drawLine(7,10,12,15);p.drawLine(12,15,17,10)
    elif name=='collapse':p.drawLine(7,14,12,9);p.drawLine(12,9,17,14)
    p.restore()


class MotionButton(QPushButton):
    def __init__(self,text,callback,name='',glyph=''):
        super().__init__(text);self.setObjectName(name);self.glyph=glyph;self.hover=0.;self.badge=None
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.clicked.connect(callback)
        self.setFont(font(14,QFont.Weight.DemiBold if name=='primary' else QFont.Weight.Normal))
        self.anim=QPropertyAnimation(self,b'hoverAmount',self);self.anim.setDuration(140);self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if text in EN:bind(self,text)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(),self.sizePolicy().verticalPolicy())
        policy=self.sizePolicy();policy.setVerticalPolicy(QSizePolicy.Policy.Preferred);policy.setHeightForWidth(True);self.setSizePolicy(policy)
        self._wrapped=None;self._wrapped_key=None

    def get_hover(self):return self.hover
    def set_hover(self,value):self.hover=value;self.update()
    hoverAmount=Property(float,get_hover,set_hover)

    def enterEvent(self,event):self.animate_to(1.);super().enterEvent(event)
    def leaveEvent(self,event):self.animate_to(0.);super().leaveEvent(event)
    def animate_to(self,value):
        self.anim.stop()
        if not motion_enabled():self.set_hover(value);return
        self.anim.setStartValue(self.hover);self.anim.setEndValue(value);self.anim.start()

    def sizeHint(self):
        quiet=self.objectName() in ('quiet','chip')
        return QSize(self.fontMetrics().horizontalAdvance(self.text())+32+(26 if self.glyph else 0)+(34 if self.badge else 0)+(18 if self.objectName()=='select' else 0),30 if quiet else 40)

    def minimumSizeHint(self):
        hint=self.sizeHint();return QSize(min(hint.width(),160),hint.height())

    def hasHeightForWidth(self):return True

    def text_space(self):return 28+(26 if self.glyph else 0)+(34 if self.badge else 0)+(18 if self.objectName()=='select' else 0)

    def text_layout(self,width):
        width=max(8,int(width));key=(self.text(),self.font().toString(),width,self.layoutDirection())
        if key!=self._wrapped_key:
            layout=QTextLayout(self.text(),self.font());option=QTextOption();option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere);option.setAlignment(Qt.AlignmentFlag.AlignHCenter);option.setTextDirection(self.layoutDirection());layout.setTextOption(option)
            layout.beginLayout();height=0.
            while True:
                line=layout.createLine()
                if not line.isValid():break
                line.setLineWidth(width);line.setPosition(QPointF(0,height));height+=line.height()
            layout.endLayout();self._wrapped=(layout,height);self._wrapped_key=key
        return self._wrapped

    def heightForWidth(self,width):
        _,height=self.text_layout(width-self.text_space())
        return max(self.sizeHint().height(),round(height)+12)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);r=QRectF(self.rect()).adjusted(1,1,-1,-1)
        role=self.objectName();t=self.hover
        if role=='primary':base,over,foreground=PRIMARY,'#37a2f2',TEXT
        elif role in ('nav','quiet'):base,over,foreground=BG,'#2b3845',MUTED
        else:base,over,foreground=FIELD,'#334556',TEXT
        if role=='nav':base=BG
        if role=='chip':base,over,foreground='#263541','#324a5d','#b4d9f6'
        if self.isChecked():foreground=TEXT
        color=mix(base,over,t)
        if self.isDown():color=color.darker(116)
        if not self.isEnabled():color=QColor('#242e38');foreground='#637383'
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(color);p.drawRoundedRect(r,5 if role=='chip' else 7,5 if role=='chip' else 7)
        if role=='nav' and self.isChecked():
            p.setPen(QPen(QColor(ACCENT),2));p.drawLine(QPointF(r.left()+8,r.bottom()),QPointF(r.right()-8,r.bottom()))
        if self.hasFocus():p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(ACCENT),1));p.drawRoundedRect(r.adjusted(1,1,-1,-1),7,7)
        textrect=r.adjusted(13,0,-13,0)
        rtl=self.layoutDirection()==Qt.LayoutDirection.RightToLeft
        if role=='select':
            x=r.left()+8 if rtl else r.right()-24
            icon(p,'chevron',QRectF(x,r.center().y()-8,16,16),foreground)
            if rtl:textrect.setLeft(textrect.left()+18)
            else:textrect.setRight(textrect.right()-18)
        if self.badge:
            x=textrect.right()-28 if rtl else textrect.left()
            self.badge.paint(p,int(x),int(r.center().y()-12),28,24)
            if rtl:textrect.setRight(textrect.right()-34)
            else:textrect.setLeft(textrect.left()+34)
        if self.glyph:
            if not self.text():
                icon(p,self.glyph,QRectF(r.center().x()-9,r.center().y()-9,18,18),foreground);return
            x=textrect.right()-18 if rtl else textrect.left()
            icon(p,self.glyph,QRectF(x,r.center().y()-9,18,18),foreground)
            if rtl:textrect.setRight(textrect.right()-26)
            else:textrect.setLeft(textrect.left()+26)
        p.setPen(QColor(foreground));p.setFont(self.font());layout,height=self.text_layout(textrect.width());layout.draw(p,QPointF(textrect.left(),r.center().y()-height/2))


class CheckBox(QCheckBox):
    def paintEvent(self,event):
        super().paintEvent(event)
        if not self.isChecked():return
        option=QStyleOptionButton();self.initStyleOption(option)
        r=self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator,option,self)
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(QPen(QColor('#ffffff'),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.drawLine(QPointF(r.left()+4,r.top()+8),QPointF(r.left()+7,r.top()+12));p.drawLine(QPointF(r.left()+7,r.top()+12),QPointF(r.left()+13,r.top()+5))


class FadeOverlay(QWidget):
    def __init__(self,parent,pixmap):
        super().__init__(parent);self.image=pixmap;self.alpha=1.;self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet('background: transparent;');self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setGeometry(parent.rect());self.show()
    def get_alpha(self):return self.alpha
    def set_alpha(self,value):self.alpha=value;self.update()
    opacity=Property(float,get_alpha,set_alpha)
    def paintEvent(self,event):
        p=QPainter(self);p.setOpacity(self.alpha);p.drawPixmap(0,0,self.image)


class MotionStack(QStackedWidget):
    def __init__(self,parent=None):super().__init__(parent);self.transition=None;self.overlay=None
    def setCurrentIndex(self,index):
        if self.currentIndex()==index:return
        old=self.currentWidget();snapshot=old.grab() if old and self.isVisible() and motion_enabled() else None
        if self.transition:self.transition.stop()
        if self.overlay:self.overlay.deleteLater();self.overlay=None
        super().setCurrentIndex(index)
        if snapshot is not None:
            self.overlay=FadeOverlay(self,snapshot);self.transition=QPropertyAnimation(self.overlay,b'opacity',self)
            self.transition.setDuration(160);self.transition.setStartValue(1.);self.transition.setEndValue(0.)
            overlay=self.overlay;self.transition.finished.connect(overlay.deleteLater);self.transition.finished.connect(lambda:setattr(self,'overlay',None));self.transition.start()


def open_motion(dialog):
    native_frame(dialog)
    if not motion_enabled():return
    target=dialog.pos();group=QParallelAnimationGroup(dialog)
    move=QPropertyAnimation(dialog,b'pos',group);move.setDuration(180);move.setStartValue(target+QPointF(0,12).toPoint());move.setEndValue(target);move.setEasingCurve(QEasingCurve.Type.OutCubic);group.addAnimation(move)
    if QApplication.platformName()!='offscreen':
        opacity=QPropertyAnimation(dialog,b'windowOpacity',group);opacity.setDuration(160);opacity.setStartValue(0.);opacity.setEndValue(1.);group.addAnimation(opacity)
    dialog.open_animation=group;group.start()
