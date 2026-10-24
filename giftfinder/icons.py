"""Cached Qt-rendered flags and currency badges, loaded only outside painting."""
from functools import lru_cache
from pathlib import Path
import json
import math
from PySide6.QtCore import Qt,QRectF,QPointF
from PySide6.QtGui import QIcon,QPixmap,QPainter,QPainterPath,QPen,QColor,QPolygonF,QFont
from PySide6.QtSvg import QSvgRenderer
from .design import font

COUNTRIES={'en':'gb','ru':'ru','uk':'ua','de':'de','fr':'fr','es':'es','it':'it',
    'pt_PT':'pt','pt_BR':'br','pl':'pl','cs':'cz','nl':'nl','sv':'se','tr':'tr',
    'ar':'sa','he':'il','fa':'ir','hi':'in','bn':'bd','ur':'pk','id':'id','ms':'my',
    'vi':'vn','th':'th','zh_CN':'cn','zh_TW':'tw','ja':'jp','ko':'kr'}

@lru_cache(maxsize=32)
def flag_icon(code):
    image=QPixmap(36,28);image.fill(Qt.GlobalColor.transparent);p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    if code=='system':
        p.setPen(QPen(QColor('#a3bdd1'),1.7));p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(5,4,26,17),2,2);p.drawLine(18,21,18,25);p.drawLine(12,25,24,25)
    else:
        rect=QRectF(2,3,32,23);clip=QPainterPath();clip.addRoundedRect(rect,3,3);p.setClipPath(clip)
        svg=QSvgRenderer(str(Path(__file__).parent/'flags'/(COUNTRIES.get(code,'gb')+'.svg')))
        svg.render(p,rect);p.setClipping(False);p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(220,235,245,45),1));p.drawRoundedRect(rect,3,3)
    p.end();return QIcon(image)

@lru_cache(maxsize=1)
def symbols():return json.loads((Path(__file__).parent/'locales/currency-symbols.json').read_text(encoding='utf-8'))

@lru_cache(maxsize=200)
def currency_icon(code):
    image=QPixmap(32,32);image.fill(Qt.GlobalColor.transparent);p=QPainter(image);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#293e50'));p.drawEllipse(QRectF(1,1,30,30))
    p.setPen(QColor('#8ac8fb'));p.setFont(font(18))
    if code=='GRAM':
        p.setPen(QPen(QColor('#74c1ff'),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
        p.drawPolygon(QPolygonF([QPointF(7,10),QPointF(25,10),QPointF(16,25)]));p.drawLine(16,10,16,25)
    elif code=='Stars':
        points=[QPointF(16+math.sin(i*math.pi/5)*(10 if i%2==0 else 4.5),16-math.cos(i*math.pi/5)*(10 if i%2==0 else 4.5)) for i in range(10)]
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#ffd074'));p.drawPolygon(QPolygonF(points))
    else:
        text='¤' if code=='ORIGINAL' else symbols().get(code,code)
        if len(text)>2:p.setFont(font(10,QFont.Weight.DemiBold))
        p.drawText(QRectF(1,0,30,31),Qt.AlignmentFlag.AlignCenter,text)
    p.end();return QIcon(image)
