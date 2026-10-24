from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt, QSize, QRectF, QPointF, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget, QPushButton,
                               QListView, QLineEdit, QStyledItemDelegate, QStyle, QCheckBox, QComboBox,
                               QGridLayout, QSizeGrip, QFrame)

from .core import SearchQuery, MARKETS, compact, norm
from .ui_common import button, label
from .previews import asset_url
from .views import CardView
from .design import CheckBox
from .i18n import tr, bind, refresh_tree, theme_name
from .controls import SearchSelector
from . import monochrome


class DragHeader(QWidget):
    def __init__(self,parent,title,subtitle='',close_button=True):
        super().__init__(parent)
        self.anchor=None
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        titles=QVBoxLayout();titles.setSpacing(3)
        titles.addWidget(label(title,'windowTitle'))
        if subtitle:titles.addWidget(label(subtitle,'muted'))
        layout.addLayout(titles,1)
        if close_button:
            close=button('',parent.close,'quiet','close');close.setFixedSize(32,32);layout.addWidget(close)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            animation=getattr(self.window(),'open_animation',None)
            if animation:animation.stop();self.window().setWindowOpacity(1.)
            self.anchor=event.globalPosition().toPoint()-self.window().pos()
            event.accept()

    def mouseMoveEvent(self,event):
        if self.anchor is not None and event.buttons()&Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint()-self.anchor)
            event.accept()

    def mouseReleaseEvent(self,event):
        self.anchor=None


class TileModel(QAbstractListModel):
    def __init__(self,rows=()):
        super().__init__();self.rows=list(rows)

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        row=self.rows[index.row()]
        if role==Qt.ItemDataRole.UserRole:return row
        if role==Qt.ItemDataRole.DisplayRole:return row['name']
        if role==Qt.ItemDataRole.SizeHintRole:return QSize(160,202)
        if role==Qt.ItemDataRole.ToolTipRole:return row['name']+'\n'+row.get('subtitle','')

    def replace(self,rows):
        self.beginResetModel();self.rows=list(rows);self.endResetModel()


class TileDelegate(QStyledItemDelegate):
    def __init__(self,renderer,selected=lambda _:False,backdrop=lambda:'',parent=None,cell=None,ribbon=False):
        super().__init__(parent);self.renderer=renderer;self.selected=selected;self.backdrop=backdrop;self.cell=cell or QSize(160,202);self.ribbon=ribbon

    def sizeHint(self,option,index):return self.cell

    def paint(self,p,option,index):
        from .design import font,mix,ACCENT,PANEL,TEXT,MUTED
        row=index.data(Qt.ItemDataRole.UserRole)
        if not row:return
        view=self.parent();hover=view.hover_for(index) if isinstance(view,CardView) else 0.
        selected=self.selected(row);kind=row.get('kind')
        p.save();p.setClipRect(option.rect,Qt.ClipOperation.IntersectClip);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r=QRectF(option.rect.x()+5,option.rect.y()+5,self.cell.width()-12,self.cell.height()-12)
        p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(Qt.PenStyle.NoPen)
        if kind=='color':
            art=QRectF(r.left(),r.top(),r.width(),self.cell.height()-62)
            p.setBrush(QColor('#26323e'));p.drawRoundedRect(art,10,10)
            colors=[row['color']] if row['key'] else list(monochrome.COLORS.values())[4:10]
            diameter=34 if row['key'] else 25
            span=diameter+(len(colors)-1)*17
            for i,color in enumerate(colors):
                p.setPen(QPen(QColor(color).lighter(125),1));p.setBrush(QColor(color))
                p.drawEllipse(QRectF(art.center().x()-span/2+i*17,art.center().y()-diameter/2,diameter,diameter))
            if hover or selected:
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(ACCENT),2 if selected else hover));p.drawRoundedRect(art.adjusted(.5,.5,-.5,-.5),10,10)
            p.setFont(font(13,QFont.Weight.DemiBold));p.setPen(QColor(TEXT))
            p.drawText(QRectF(r.left(),art.bottom()+7,r.width(),33),Qt.TextFlag.TextWordWrap,row['name'])
            p.setFont(font(11));p.setPen(QColor(MUTED));p.drawText(QRectF(r.left(),r.bottom()-13,r.width(),17),row.get('subtitle',''))
            p.restore();return
        if self.ribbon:
            p.setClipRect(r,Qt.ClipOperation.IntersectClip)
            tint=QColor(row.get('color','#70899a'));tint.setAlpha(27);p.setPen(Qt.PenStyle.NoPen);p.setBrush(tint);p.drawRoundedRect(r,11,11)
            for i,(collection,model) in enumerate(row.get('members',[])[:1]):
                if row.get('key')=='monochrome':
                    box=QRectF(r.right()-70,r.center().y()-32,64,64)
                    key=self.renderer.paint(p,box,collection,model,monochrome.backgrounds(collection,model)[0])
                    if isinstance(view,CardView):view.watch(key,index)
                    continue
                url=asset_url('model',collection,model,256);image=self.renderer.assets.get(url)
                if isinstance(view,CardView):view.watch(('asset',url),index)
                if image:
                    box=QRectF(r.right()-70,r.center().y()-32,64,64)
                    p.drawPixmap(box,image,QRectF(image.rect()))
            title=row['name']
            p.setFont(font(15,QFont.Weight.DemiBold));p.setPen(QColor(TEXT))
            p.drawText(QRectF(r.left()+12,r.top()+11,r.width()-88,44),Qt.TextFlag.TextWordWrap,title)
            p.setFont(font(12));p.setPen(QColor(MUTED));p.drawText(QRectF(r.left()+12,r.bottom()-27,r.width()-24,20),tr('models_count',count=len(row.get('members',[]))))
            if hover:
                p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(ACCENT),hover));p.drawRoundedRect(r.adjusted(.5,.5,-.5,-.5),11,11)
            p.restore();return
        art=QRectF(r.left(),r.top(),r.width(),r.width())
        if kind=='backdrop':
            key=self.renderer.paint(p,art,'',backdrop=row['name'])
            if isinstance(view,CardView):view.watch(key,index)
        elif kind=='symbol':
            p.setBrush(QColor('#2d3c4a'));p.setPen(Qt.PenStyle.NoPen);p.drawRoundedRect(art,10,10)
            url=asset_url('symbol',row['collection'],row['name'],128);image=self.renderer.assets.get(url)
            if isinstance(view,CardView):view.watch(('asset',url),index)
            if image:p.drawPixmap(art.adjusted(32,20,-32,-20),image,QRectF(image.rect()))
        elif kind=='theme':
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(row.get('color','#507080')).darker(175));p.drawRoundedRect(art,10,10)
            for i,(collection,model) in enumerate(row.get('members',[])[:4]):
                if row.get('key')=='monochrome':
                    box=QRectF(art.left()+(i%2)*art.width()/2,art.top()+(i//2)*art.height()/2,art.width()/2,art.height()/2)
                    key=self.renderer.paint(p,box,collection,model,monochrome.backgrounds(collection,model)[0])
                    if isinstance(view,CardView):view.watch(key,index)
                    continue
                url=asset_url('model',collection,model,256);image=self.renderer.assets.get(url)
                if isinstance(view,CardView):view.watch(('asset',url),index)
                if image:p.drawPixmap(QRectF(art.left()+(i%2)*art.width()/2,art.top()+(i//2)*art.height()/2,art.width()/2,art.height()/2),image,QRectF(image.rect()))
        else:
            key=self.renderer.paint(p,art,row.get('collection',''),row['name'] if kind=='model' else '',self.backdrop())
            if isinstance(view,CardView):view.watch(key,index)
        if hover and not selected:
            p.setPen(QPen(QColor(ACCENT),hover));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRoundedRect(art,12,12)
        width=int(r.width());p.setPen(QColor(TEXT));p.setFont(font(13,QFont.Weight.DemiBold))
        p.drawText(QRectF(r.left(),art.bottom()+8,width,37),Qt.TextFlag.TextWordWrap,row['name'])
        p.setFont(font(11));p.setPen(QColor(MUTED))
        p.drawText(QRectF(r.left(),art.bottom()+47,width,29),Qt.TextFlag.TextWordWrap,row.get('subtitle',''))
        if selected:
            p.setPen(QPen(QColor(ACCENT),2));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRoundedRect(art.adjusted(-1,-1,1,1),12,12)
            box=QRectF(r.right()-27,r.top()+8,20,20);p.setBrush(QColor(ACCENT));p.setPen(Qt.PenStyle.NoPen);p.drawEllipse(box)
            p.setPen(QPen(QColor('#162633'),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            p.drawLine(QPointF(box.left()+5,box.top()+10),QPointF(box.left()+9,box.top()+14));p.drawLine(QPointF(box.left()+9,box.top()+14),QPointF(box.left()+15,box.top()+6))
        p.restore()


class FilterDialog(QDialog):
    applied=Signal(object,object)

    def __init__(self,window,query=None,extra=None):
        super().__init__(window,Qt.WindowType.Dialog|Qt.WindowType.WindowTitleHint|Qt.WindowType.WindowCloseButtonHint|Qt.WindowType.WindowMaximizeButtonHint)
        self.window_ref=window;self.catalog=window.catalog;self.renderer=window.renderer
        self.state=replace(query if query is not None else window.filter_query)
        if self.state.mono_colors:self.state=replace(self.state,monochrome=True)
        self.extra=dict(window.filter_extra if extra is None else extra)
        if self.state.models and not self.state.targets:
            rows=self.catalog.selected_models(self.state)
            self.state=replace(self.state,models=(),targets=tuple((r['collection'],r['name']) for r in rows))
        self.category='collections';self.all_rows=[]
        self.setWindowTitle(tr('filters'));self.resize(1140,790);self.setMinimumSize(760,560);self.setSizeGripEnabled(True)
        layout=QVBoxLayout(self);layout.setContentsMargins(22,20,22,12);layout.setSpacing(12)
        self.header=DragHeader(self,'filters',close_button=False)
        layout.addWidget(self.header)
        self.summary=label('','muted',True);layout.addWidget(self.summary)
        tabs=QHBoxLayout();self.tabs={}
        for key,title in (('colors','color'),('collections','collection'),('models','model'),('backdrops','backdrop'),('symbols','symbol'),('themes','themes')):
            b=button(title,lambda checked=False,k=key:self.change_tab(k),'nav');b.setCheckable(True)
            self.tabs[key]=b;tabs.addWidget(b)
        tabs.addStretch();layout.addLayout(tabs)
        self.search=QLineEdit();bind(self.search,'search_list','setPlaceholderText');self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.filter_rows);layout.addWidget(self.search)
        self.grid=CardView(self.renderer,cell=QSize(178,256));self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setMovement(QListView.Movement.Static);self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setGridSize(QSize(178,256));self.grid.setUniformItemSizes(True);self.grid.setMouseTracking(True)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows=TileModel();self.grid.setModel(self.rows)
        self.grid.setItemDelegate(TileDelegate(self.renderer,self.is_selected,lambda:self.state.backdrops[0] if self.state.backdrops else '',self.grid,cell=QSize(178,256)))
        self.grid.clicked.connect(self.choose);layout.addWidget(self.grid,1)
        self.grid_note=label('','tiny',True);self.grid_note.hide()
        markets=QHBoxLayout();self.market_checks={}
        for key,(title,_) in MARKETS.items():
            check=CheckBox(title);check.setChecked(key in self.state.markets);self.market_checks[key]=check;markets.addWidget(check)
        layout.addLayout(markets)
        values=QHBoxLayout()
        values.addWidget(label('price','muted'))
        self.minimum=QLineEdit(self.extra.get('min',''));bind(self.minimum,'from','setPlaceholderText');self.minimum.setMaximumWidth(100)
        self.maximum=QLineEdit(self.extra.get('max',''));bind(self.maximum,'to','setPlaceholderText');self.maximum.setMaximumWidth(100)
        self.unit=SearchSelector();self.unit.setMaximumWidth(150);self.unit.addItem('GRAM','GRAM');self.unit.addItem('Stars','Stars')
        for code in ('RUB','USD','EUR'):
            self.unit.addItem(code,code)
        for code in window.ratebook.currencies():
            if self.unit.findData(code)<0:self.unit.addItem(code,code)
        saved=self.extra.get('unit','GRAM');self.unit.setCurrentIndex(max(0,self.unit.findData('GRAM' if saved=='TON' else saved)))
        self.number=QLineEdit(str(self.state.number or ''));bind(self.number,'gift_number','setPlaceholderText');self.number.setMaximumWidth(175)
        for w in (self.minimum,self.maximum,self.unit):values.addWidget(w)
        values.addStretch();values.addWidget(self.number);layout.addLayout(values)
        footer=QHBoxLayout();footer.addWidget(button('reset',self.reset,'quiet'));footer.addStretch()
        self.error=label('','muted');footer.addWidget(self.error)
        footer.addWidget(button('cancel',self.reject));footer.addWidget(button('apply',self.apply,'primary'));footer.addWidget(QSizeGrip(self))
        layout.addLayout(footer)
        self.change_tab('collections')
        geometry=window.store.data['settings'].get('filter_geometry')
        if isinstance(geometry,list) and len(geometry)==4:
            self.resize(max(760,geometry[2]),max(560,geometry[3]))

    def retranslate(self):
        self.setWindowTitle(tr('filters'));refresh_tree(self);self.unit.retranslate();self.populate()

    def redraw_grid(self,*_):
        self.grid.viewport().update()

    def change_tab(self,key):
        self.category=key
        for k,button in self.tabs.items():button.setChecked(k==key)
        cell=QSize(178,142 if key=='colors' else 256)
        self.grid.setGridSize(cell);self.grid.itemDelegate().cell=cell;self.grid.doItemsLayout()
        self.search.clear();self.populate();self.grid.scrollToTop()

    def populate(self):
        c=self.catalog;key=self.category
        self.tabs['colors'].setVisible(self.state.monochrome or bool(self.state.mono_colors))
        if key=='colors':
            from collections import Counter
            candidates=c.selected_models(replace(self.state,monochrome=True,mono_colors=()))
            counts=Counter(monochrome.family(r['collection'],r['name']) for r in candidates)
            self.all_rows=[{'kind':'color','name':tr('all_colors'),'key':'','color':'','subtitle':tr('models_count',count=len(candidates))}]
            self.all_rows.extend({'kind':'color','name':tr('color_'+color),'key':color,'color':hexcode,'subtitle':tr('models_count',count=counts[color])} for color,hexcode in monochrome.COLORS.items())
        elif key=='collections':
            self.all_rows=[{'kind':'collection','name':name,'collection':name,'key':name,
                            'subtitle':tr('models_count',count=len(c.data.get('traits',{}).get(name,{}).get('models',[])))} for name in c.data['collections']]
        elif key=='models':
            query=replace(self.state,models=(),targets=())
            self.all_rows=[{**r,'kind':'model','subtitle':str(r.get('rarity',''))+'%' if self.state.collection and r.get('rarity') is not None else r['collection']} for r in c.selected_models(query)]
            if self.state.collection or self.state.theme:
                self.renderer.assets.prefetch(asset_url('model',r['collection'],r['name'],256) for r in self.all_rows)
        elif key=='backdrops':
            self.all_rows=[{'kind':'backdrop','name':r['name'],'key':r['name'],'subtitle':self.renderer.palette(r['name'])[0].upper()} for r in c.data['backdrops']]
            if self.state.monochrome:
                possible={b for r in c.selected_models(replace(self.state,backdrops=())) for b in monochrome.backgrounds(r['collection'],r['name'])}
                self.all_rows=[r for r in self.all_rows if r['name'] in possible]
        elif key=='symbols':
            collections={r['collection'] for r in c.selected_models(replace(self.state,models=(),targets=()))}
            unique={}
            for r in c.symbol_rows:
                if r['collection'] in collections and r['name'] not in unique:
                    unique[r['name']]={**r,'kind':'symbol','key':r['name'],'subtitle':''}
            self.all_rows=list(unique.values())
        else:
            self.all_rows=[{**r,'name':theme_name(key),'kind':'theme','key':key,'subtitle':tr('models_count',count=len(r['members']))} for key,r in c.themes.items()]
        if key!='colors':self.all_rows.sort(key=lambda r:norm(r['name']))
        for row in self.all_rows:row['_search']=norm(row['name']+' '+row.get('subtitle',''))
        self.filter_rows();self.update_summary()

    def filter_rows(self):
        term=norm(self.search.text())
        self.rows.replace([r for r in self.all_rows if not term or term in r.get('_search',norm(r['name']))])

    def is_selected(self,row):
        kind=row['kind'];state=self.state
        if kind=='color':return row['key'] in state.mono_colors if row['key'] else not state.mono_colors
        if kind=='collection':return state.collection==row['name']
        if kind=='theme':return state.monochrome if row['key']=='monochrome' else state.theme==row['key']
        if kind=='model':return (row['collection'],row['name']) in state.targets
        return row['name'] in (state.backdrops if kind=='backdrop' else state.symbols)

    def choose(self,index):
        row=index.data(Qt.ItemDataRole.UserRole)
        if not row:return
        kind=row['kind']
        if kind=='color':
            values=list(self.state.mono_colors);color=row['key']
            if not color:values=[]
            elif color in values:values.remove(color)
            else:values.append(color)
            self.state=replace(self.state,monochrome=True,mono_colors=tuple(values))
            self.grid.viewport().update();self.update_summary();return
        if kind=='collection':
            collection='' if self.state.collection==row['name'] else row['name']
            targets=tuple(p for p in self.state.targets if not collection or p[0]==collection)
            self.state=replace(self.state,collection=collection,targets=targets,models=())
            if collection:
                self.renderer.assets.prefetch(asset_url('model',collection,r['name'],256) for r in self.catalog.data['traits'].get(collection,{}).get('models',[]))
            self.change_tab('models');return
        if kind=='theme':
            if row['key']=='monochrome':
                enable=not self.state.monochrome
                self.state=replace(self.state,monochrome=enable,mono_colors=self.state.mono_colors if enable else ())
                if enable:self.change_tab('colors');return
            else:self.state=replace(self.state,theme='' if self.state.theme==row['key'] else row['key'],targets=(),models=())
        elif kind=='model':
            pair=(row['collection'],row['name']);values=list(self.state.targets)
            values.remove(pair) if pair in values else values.append(pair)
            self.state=replace(self.state,targets=tuple(values),models=())
        else:
            field='backdrops' if kind=='backdrop' else 'symbols';values=list(getattr(self.state,field))
            values.remove(row['name']) if row['name'] in values else values.append(row['name'])
            self.state=replace(self.state,**{field:tuple(values)})
        self.grid.viewport().update();self.update_summary()

    def update_summary(self):
        self.tabs['colors'].setVisible(self.state.monochrome or bool(self.state.mono_colors))
        parts=[self.state.collection] if self.state.collection else []
        if self.state.theme:parts.append(theme_name(self.state.theme))
        if self.state.monochrome:parts.append(tr('theme_monochrome'))
        if self.state.mono_colors:parts.append(tr('color')+': '+', '.join(tr('color_'+color) for color in self.state.mono_colors))
        if self.state.targets:parts.append(tr('selected_models',count=len(self.state.targets)))
        if self.state.backdrops:parts.append(tr('backdrop')+': '+', '.join(self.state.backdrops))
        if self.state.symbols:parts.append(tr('symbol')+': '+', '.join(self.state.symbols))
        self.summary.setText(' · '.join(parts));self.summary.setVisible(bool(parts))

    def reset(self):
        self.state=SearchQuery();self.minimum.clear();self.maximum.clear();self.number.clear()
        for check in self.market_checks.values():check.setChecked(True)
        self.change_tab('collections')

    def apply(self):
        from decimal import Decimal,InvalidOperation
        try:
            bounds=[Decimal(edit.text().strip().replace(',','.')) if edit.text().strip() else None for edit in (self.minimum,self.maximum)]
            if any(v is not None and (not v.is_finite() or v<0) for v in bounds):raise InvalidOperation
            if all(v is not None for v in bounds) and bounds[1]<bounds[0]:raise InvalidOperation
        except InvalidOperation:
            self.error.setText(tr('invalid_price'));return
        raw=self.number.text().strip().lstrip('#')
        if raw and (not raw.isdigit() or int(raw)<=0):
            self.error.setText(tr('invalid_number'));return
        markets=tuple(k for k,v in self.market_checks.items() if v.isChecked())
        if not markets:self.error.setText(tr('choose_market'));return
        self.state=replace(self.state,number=int(raw) if raw else None,markets=markets)
        extra={'min':self.minimum.text(),'max':self.maximum.text(),'unit':self.unit.currentData()}
        self.applied.emit(self.state,extra);self.close()

    def done(self,result):
        r=self.geometry();self.window_ref.store.data['settings']['filter_geometry']=[r.x(),r.y(),r.width(),r.height()]
        self.window_ref.store.save();super().done(result)
