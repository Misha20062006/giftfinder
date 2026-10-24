from collections import defaultdict

from PySide6.QtCore import QSize,Qt,QModelIndex,Property,QPropertyAnimation,QEasingCurve
from PySide6.QtWidgets import QListView,QAbstractItemView
from .design import motion_enabled


class CardView(QListView):
    """Only repaint visible cards whose artwork actually changed."""
    def __init__(self,renderer,parent=None,cell=QSize(260,310)):
        super().__init__(parent);self.renderer=renderer;self.watched=defaultdict(set)
        self.setViewMode(QListView.ViewMode.IconMode);self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust);self.setGridSize(cell);self.setUniformItemSizes(True)
        self.setMouseTracking(True);self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.hovered_row=-1;self.previous_row=-1;self.hover_amount=1.
        self.hover_animation=QPropertyAnimation(self,b'hoverValue',self);self.hover_animation.setDuration(140);self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.scroll_animation=QPropertyAnimation(self.verticalScrollBar(),b'value',self)
        self.scroll_animation.setDuration(170);self.scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.verticalScrollBar().sliderPressed.connect(self.scroll_animation.stop)
        renderer.changed.connect(self.refresh_key);renderer.assets.ready.connect(self.refresh_asset)

    def setModel(self,model):
        super().setModel(model)
        model.modelReset.connect(self.watched.clear);model.layoutChanged.connect(self.watched.clear)
        model.modelReset.connect(self.reset_hover);model.layoutChanged.connect(self.reset_hover)

    def reset_hover(self):
        self.hover_animation.stop();self.hovered_row=-1;self.previous_row=-1;self.hover_amount=1.

    def mousePressEvent(self,event):
        self.scroll_animation.stop();super().mousePressEvent(event)

    def get_hover(self):return self.hover_amount
    def set_hover(self,value):
        self.hover_amount=value
        for row in (self.hovered_row,self.previous_row):
            if row>=0 and self.model():self.viewport().update(self.visualRect(self.model().index(row,0)).adjusted(-4,-4,4,4))
    hoverValue=Property(float,get_hover,set_hover)

    def hover_for(self,index):
        if index.row()==self.hovered_row:return self.hover_amount
        if index.row()==self.previous_row:return 1.-self.hover_amount
        return 0.

    def set_hover_row(self,row):
        if self.hovered_row==row:return
        self.previous_row=self.hovered_row;self.hovered_row=row;self.hover_animation.stop()
        if not motion_enabled():self.set_hover(1.);return
        self.hover_animation.setStartValue(0.);self.hover_animation.setEndValue(1.);self.hover_animation.start()

    def mouseMoveEvent(self,event):
        self.set_hover_row(self.indexAt(event.position().toPoint()).row());super().mouseMoveEvent(event)

    def leaveEvent(self,event):self.set_hover_row(-1);super().leaveEvent(event)

    def wheelEvent(self,event):
        if event.pixelDelta().y() or not motion_enabled():super().wheelEvent(event);return
        delta=event.angleDelta().y()
        if not delta:super().wheelEvent(event);return
        bar=self.verticalScrollBar()
        running=self.scroll_animation.state()==QPropertyAnimation.State.Running
        target=(self.scroll_animation.endValue() if running else bar.value())-delta
        self.scroll_animation.stop();self.scroll_animation.setStartValue(bar.value());self.scroll_animation.setEndValue(max(bar.minimum(),min(bar.maximum(),target)));self.scroll_animation.start();event.accept()

    def watch(self,key,index):
        if key is not None:self.watched[key].add(index.row())

    def dataChanged(self,topLeft,bottomRight,roles=()):
        # Price/text changes cannot alter this view's fixed-size card geometry.
        # QListView otherwise invalidates all item rectangles, including 2400
        # offscreen entries, even though no SizeHintRole changed.
        if roles and Qt.ItemDataRole.SizeHintRole not in roles:
            QAbstractItemView.dataChanged(self,topLeft,bottomRight,roles)
        else:super().dataChanged(topLeft,bottomRight,roles)

    def refresh_asset(self,url):self.refresh_key(('asset',url))

    def refresh_key(self,key):
        model=self.model()
        if model is None or not self.isVisible():return
        viewport=self.viewport()
        for row in tuple(self.watched.get(key,())):
            rect=self.visualRect(model.index(row,0))
            if rect.intersects(viewport.rect()):viewport.update(rect)
