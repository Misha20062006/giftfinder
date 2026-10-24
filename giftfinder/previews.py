from __future__ import annotations

import hashlib
import math
from collections import OrderedDict,defaultdict
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QObject,Signal,QTimer,QUrl,QRectF,QPointF,Qt,QSize,QRunnable,QThreadPool
from PySide6.QtGui import QColor,QPainter,QPainterPath,QPixmap,QRadialGradient,QImage
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply

from .core import safe_url,norm


@lru_cache(maxsize=32768)
def asset_url(kind,collection,name='',size=256):
    if kind=='collection':return f'https://api.changes.tg/original/{quote(collection,safe="")}.png?size={size}'
    path='model' if kind=='model' else 'pattern'
    return f'https://api.changes.tg/{path}/{quote(collection,safe="")}/{quote(name,safe="")}.png?size={size}'


class WorkSignals(QObject):
    done=Signal(object,object)


class ImageWork(QRunnable):
    def __init__(self,key,fn):
        super().__init__();self.key=key;self.fn=fn;self.signals=WorkSignals()

    def run(self):
        try:image=self.fn()
        except Exception:image=QImage()
        self.signals.done.emit(self.key,image)


class Assets(QObject):
    ready=Signal(str)

    def __init__(self,directory,parent=None):
        super().__init__(parent)
        self.directory=Path(directory)/'images';self.directory.mkdir(parents=True,exist_ok=True)
        self.seed=Path(__file__).parent/'preview_seed';self.manager=QNetworkAccessManager(self)
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(4)
        self.cache=OrderedDict();self.images={};self.pending=set();self.queue=[];self.active=0;self.failed=set();self.offline=False
        self.jobs={};self.network_started=0;self.decoded=0

    @staticmethod
    @lru_cache(maxsize=32768)
    def key(url):return hashlib.sha256(url.encode('utf-8')).hexdigest()+'.png'

    def get(self,url,prefetch=False):
        # No file access, decoding or smooth scaling in a paint callback.
        if url in self.cache:
            self.cache.move_to_end(url);return self.cache[url]
        if url in self.failed:return None
        if url in self.pending:
            if not prefetch and url in self.queue:self.queue.remove(url);self.queue.insert(0,url)
            return None
        url=safe_url(url,True)
        if not url:return None
        self.pending.add(url)
        paths=(self.directory/self.key(url),self.seed/self.key(url))
        def load():
            for path in paths:
                if path.is_file():
                    image=QImage(str(path))
                    if not image.isNull():return image
            return QImage()
        self.start_job(url,load,lambda key,img:self.disk_ready(key,img,prefetch),0 if prefetch else 10)
        return None

    def image(self,url):
        self.get(url);return self.images.get(url)

    def start_job(self,key,fn,done,priority=0):
        task=ImageWork(key,fn);self.jobs[id(task)]=task
        def finished(k,img):
            self.jobs.pop(id(task),None);done(k,img)
        task.signals.done.connect(finished);self.pool.start(task,priority)

    def disk_ready(self,url,image,prefetch):
        if not image.isNull():self.remember(url,image);return
        if self.offline:
            self.pending.discard(url);self.failed.add(url);self.ready.emit(url);return
        self.queue.append(url) if prefetch else self.queue.insert(0,url)
        self.pump()

    def remember(self,url,image):
        self.images[url]=image;self.cache[url]=QPixmap.fromImage(image);self.cache.move_to_end(url)
        while len(self.cache)>900:
            expired,_=self.cache.popitem(last=False);self.images.pop(expired,None)
        self.pending.discard(url);self.decoded+=1;self.ready.emit(url)

    def pump(self):
        while self.active<6 and self.queue:
            url=self.queue.pop(0);self.active+=1;self.network_started+=1
            request=QNetworkRequest(QUrl(url));request.setTransferTimeout(15000)
            request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            reply=self.manager.get(request)
            reply.downloadProgress.connect(lambda size,total,r=reply:r.abort() if size>8_000_000 else None)
            reply.finished.connect(lambda r=reply,u=url:self.finish(u,r))

    def finish(self,url,reply):
        raw=bytes(reply.readAll()) if reply.error()==QNetworkReply.NetworkError.NoError else b''
        self.active-=1;reply.deleteLater();self.pump()
        path=self.directory/self.key(url)
        def decode():
            image=QImage.fromData(raw)
            if not image.isNull():image.save(str(path),'PNG')
            return image
        self.start_job(url,decode,self.network_ready,10)

    def network_ready(self,url,image):
        if image.isNull():self.pending.discard(url);self.failed.add(url);self.ready.emit(url)
        else:self.remember(url,image)

    def prefetch(self,urls):
        for url in urls:self.get(url,prefetch=True)


def compose(width,height,dpr,palette,model,pattern):
    output=QImage(round(width*dpr),round(height*dpr),QImage.Format.Format_ARGB32_Premultiplied)
    output.setDevicePixelRatio(dpr);output.fill(Qt.GlobalColor.transparent)
    p=QPainter(output);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect=QRectF(0,0,width,height);clip=QPainterPath();clip.addRoundedRect(rect,12,12);p.setClipPath(clip)
    center,edge,color=palette
    gradient=QRadialGradient(QPointF(width/2,height*.48),max(width,height)*.6)
    gradient.setColorAt(0,QColor(center));gradient.setColorAt(1,QColor(edge));p.fillRect(rect,gradient)
    if pattern is not None:
        tinted=QImage(pattern.size(),QImage.Format.Format_ARGB32_Premultiplied);tinted.fill(Qt.GlobalColor.transparent)
        t=QPainter(tinted);t.drawImage(0,0,pattern);t.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        t.fillRect(tinted.rect(),QColor(color));t.end();p.setOpacity(.24)
        for ring,count,offset in ((.34,7,.1),(.57,10,.25)):
            for i in range(count):
                angle=2*math.pi*(i/count+offset);size=width*.13
                x=width/2+width*ring*math.cos(angle)-size/2;y=height/2+height*ring*math.sin(angle)-size/2
                p.drawImage(QRectF(x,y,size,size),tinted)
        p.setOpacity(1)
    if model is not None:
        scaled=model.scaled(QSize(round(width*.88*dpr),round(height*.93*dpr)),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation)
        p.drawImage(QRectF((width-scaled.width()/dpr)/2,(height-scaled.height()/dpr)/2,scaled.width()/dpr,scaled.height()/dpr),scaled)
    p.end();return output


class PreviewRenderer(QObject):
    changed=Signal(object)

    def __init__(self,catalog,assets):
        super().__init__(assets);self.catalog=catalog;self.assets=assets
        self.pool=QThreadPool(self);self.pool.setMaxThreadCount(4)
        self.cache=OrderedDict();self.cache_bytes=0;self.specs=OrderedDict();self.dependents=defaultdict(set);self.jobs={};self.versions=defaultdict(int)
        self.rendered=0;self.cache_hits=0;assets.ready.connect(self.asset_ready)

    def palette(self,backdrop):
        colors=self.catalog.backdrop_lookup.get(norm(backdrop),{}).get('hex',{})
        return (colors.get('centerColor','#354657'),colors.get('edgeColor','#22303f'),colors.get('patternColor','#142332'))

    def key(self,collection,model='',backdrop='',symbol='',width=256,height=256,dpr=1.,fallback=''):
        url=asset_url('model' if model else 'collection',collection,model,256) if collection else ''
        if url not in self.assets.failed:fallback=''
        return (collection,model,backdrop,symbol,round(width),round(height),round(dpr,2),fallback)

    def request(self,key):
        if key in self.cache:
            self.cache.move_to_end(key);self.cache_hits+=1;return self.cache[key]
        if key in self.jobs:return None
        collection,model,backdrop,symbol,width,height,dpr,fallback=key
        model_url=asset_url('model' if model else 'collection',collection,model,256) if collection else ''
        pattern_url=asset_url('symbol',collection,symbol,128) if symbol and collection else ''
        deps=tuple(u for u in (model_url,pattern_url) if u)
        image=self.assets.image(model_url) if model_url else None
        pattern=self.assets.image(pattern_url) if pattern_url else None
        if image is None and model_url in self.assets.failed and fallback:
            image=self.assets.image(fallback);deps+= (fallback,)
        self.specs[key]=deps
        for url in deps:self.dependents[url].add(key)
        while len(self.specs)>2048:
            old,urls=self.specs.popitem(last=False)
            for url in urls:self.dependents[url].discard(old)
        if model_url and image is None and model_url not in self.assets.failed:return None
        version=self.versions[key];palette=self.palette(backdrop)
        task=ImageWork(key,lambda:compose(width,height,dpr,palette,image,pattern));self.jobs[key]=task
        task.signals.done.connect(lambda k,img:self.finish(k,img,version));self.pool.start(task)
        return None

    def finish(self,key,image,version):
        self.jobs.pop(key,None)
        if version!=self.versions[key]:self.changed.emit(key);return
        if not image.isNull():
            self.drop(key);self.cache[key]=QPixmap.fromImage(image);self.cache_bytes+=image.sizeInBytes();self.rendered+=1
            while self.cache_bytes>128*1024*1024 and len(self.cache)>1:self.drop(next(iter(self.cache)))
        self.changed.emit(key)

    def drop(self,key):
        old=self.cache.pop(key,None)
        if old is not None:self.cache_bytes-=old.width()*old.height()*4

    def asset_ready(self,url):
        for key in tuple(self.dependents.get(url,())):
            self.versions[key]+=1;self.drop(key);self.changed.emit(key)

    def paint(self,painter,rect,collection,model='',backdrop='',symbol='',fallback=''):
        dpr=painter.device().devicePixelRatioF()
        key=self.key(collection,model,backdrop,symbol,rect.width(),rect.height(),dpr,fallback)
        pixmap=self.request(key)
        if pixmap:painter.drawPixmap(rect.topLeft(),pixmap)
        else:
            painter.save();painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(self.palette(backdrop)[1]));painter.drawRoundedRect(rect,12,12);painter.restore()
        return key

    def pixmap(self,collection,model='',backdrop='',symbol='',size=256,fallback=''):
        key=self.key(collection,model,backdrop,symbol,size,size,1.,fallback)
        pixmap=self.request(key)
        if pixmap:return pixmap
        blank=QPixmap(size,size);blank.fill(QColor(self.palette(backdrop)[1]));return blank
