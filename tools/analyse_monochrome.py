"""Evaluate foreground pixels against the 80 actual backdrop palettes."""
import json,math,hashlib,time,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];WORK=Path(sys.argv[1]).resolve()
CAT=json.loads((ROOT/'giftfinder/catalog_full.json').read_text(encoding='utf-8'))
MANIFEST=json.loads((WORK/'image-manifest.json').read_text(encoding='utf-8'))

def hsv(rgb):
    maximum=rgb.max(axis=-1);minimum=rgb.min(axis=-1);chroma=maximum-minimum
    saturation=np.divide(chroma,maximum,out=np.zeros_like(chroma),where=maximum>0)
    hue=np.zeros_like(maximum);valid=chroma>1e-6
    r,g,b=np.moveaxis(rgb,-1,0)
    for match,offset,a,z in ((maximum==r,0,g,b),(maximum==g,2,b,r),(maximum==b,4,r,g)):
        mask=valid&match;hue[mask]=(np.divide(a-z,chroma,out=np.zeros_like(chroma),where=valid)[mask]+offset)%6
    return hue*60,saturation,maximum,chroma

def colour(h,s,v,c):
    if s<.18 or c<.075:
        return 'black' if v<.29 else 'white' if v>.74 else 'gray'
    if 12<=h<65 and v<.65:return 'brown'
    if h<15 or h>=348:return 'red'
    if h<43:return 'orange'
    if h<70:return 'yellow'
    if h<165:return 'green'
    if h<195:return 'teal'
    if h<252:return 'blue'
    if h<285:return 'violet'
    if h<325:return 'purple'
    return 'pink'

def analyse(record):
    if record['status']!='ok':return {**record,'accepted':False,'reason':'image_unavailable'}
    image=np.asarray(Image.open(WORK/'images'/record['path']).convert('RGBA').resize((96,96),Image.Resampling.LANCZOS),dtype=np.float32)/255
    rgb=image[...,:3];h,s,v,c=hsv(rgb);mask=image[...,3]>.5
    if mask.sum()<100:return {**record,'accepted':False,'reason':'insufficient_foreground'}
    h,s,v,c,weight=[x[mask] for x in (h,s,v,c,image[...,3])]
    pixels=rgb[mask];total=float(weight.sum());chromatic=(s>=.18)&(c>=.075)&(v>.14)
    chromatic_share=float(weight[chromatic].sum()/total)
    metrics={'chromatic_share':round(chromatic_share,4),'foreground_pixels':int(mask.sum())}
    if chromatic_share>=.60:
        hue_weights=weight[chromatic]*(.45+.55*v[chromatic]);angles=h[chromatic]
        hist=np.histogram(angles,bins=72,range=(0,360),weights=hue_weights)[0]
        smooth=sum(np.roll(hist,k) for k in range(-3,4));peak=(int(np.argmax(smooth))+.5)*5
        distance=np.abs((angles-peak+180)%360-180);dominant=distance<=27.5
        hue_share=float(hue_weights[dominant].sum()/hue_weights.sum())
        support=float(weight[chromatic][dominant].sum()/total)
        metrics.update(hue_share=round(hue_share,4),support=round(support,4))
        if hue_share<.86 or support<.56:return {**record,**metrics,'accepted':False,'reason':'multiple_colours'}
        dw=hue_weights[dominant];hues=angles[dominant]
        angle=math.degrees(math.atan2(float(np.sum(np.sin(np.radians(hues))*dw)),float(np.sum(np.cos(np.radians(hues))*dw))))%360
        selected=np.where(chromatic)[0][dominant];mean=np.average(pixels[selected],axis=0,weights=dw)
        mh,ms,mv,mc=[float(a[0]) for a in hsv(mean.reshape(1,3))]
        family=colour(angle,ms,mv,mc)
        metrics.update(hue=round(angle,2),saturation=round(ms,3),brightness=round(mv,3),rgb=[round(float(x)*255) for x in mean])
    elif chromatic_share<=.17:
        neutral=~chromatic;w=weight[neutral];values=v[neutral]
        dark=float(w[values<.29].sum()/total);light=float(w[values>.78].sum()/total)
        if dark>.24 and light>.24:return {**record,**metrics,'accepted':False,'reason':'black_white_contrast'}
        order=np.argsort(values);median=float(values[order][np.searchsorted(np.cumsum(w[order]),w.sum()/2)])
        mean=np.average(pixels[neutral],axis=0,weights=w)
        family='black' if median<.29 else 'white' if median>.74 else 'gray'
        metrics.update(hue=0,saturation=0,brightness=round(median,3),support=round(1-chromatic_share,4),rgb=[round(float(x)*255) for x in mean])
    else:return {**record,**metrics,'accepted':False,'reason':'mixed_neutral_colour'}
    return {**record,**metrics,'accepted':True,'family':family,'reason':'dominant_family'}

def backdrops():
    rows=[]
    for row in CAT['backdrops']:
        rgb=np.array([[int(row['hex'][key][i:i+2],16)/255 for i in (1,3,5)] for key in ('centerColor','edgeColor')])
        mean=rgb[0]*.75+rgb[1]*.25
        h,s,v,c=[float(a[0]) for a in hsv(mean.reshape(1,3))]
        rows.append({**row,'family':colour(h,s,v,c),'hue':round(h,2),'saturation':round(s,3),'brightness':round(v,3)})
    return rows

if __name__=='__main__':
    palettes=backdrops();results=[];pairs=[]
    for i,record in enumerate(MANIFEST):
        row=analyse(record);matches=[]
        if row['accepted']:
            for backdrop in palettes:
                hue_distance=abs((row['hue']-backdrop['hue']+180)%360-180)
                if row['family'] in ('black','gray','white'):
                    if backdrop['saturation']>.11:continue
                    if abs(row['brightness']-backdrop['brightness'])>.25:continue
                    if row['family']=='black' and backdrop['brightness']>=.32:continue
                    if row['family']=='white' and backdrop['brightness']<=.65:continue
                    if row['family']=='gray' and not .30<=backdrop['brightness']<=.75:continue
                else:
                    if backdrop['saturation']<.20 or hue_distance>20:continue
                    if abs(row['brightness']-backdrop['brightness'])>.38:continue
                    if abs(row['saturation']-backdrop['saturation'])>.55:continue
                matches.append(backdrop['name'])
        row['backdrops']=matches;results.append(row)
        if matches:pairs.append({'collection':row['collection'],'model':row['model'],'backdrops':matches,'family':row['family'],'rgb':row['rgb']})
        if (i+1)%1000==0:print('Analyzed',i+1,flush=True)
    (WORK/'colour-audit.json').write_text(json.dumps({'method':'foreground HSV v3; transparent pixels excluded; strict dominant hue; multi-colour and high-contrast neutral patterns excluded','models':results,'backdrops':palettes},ensure_ascii=False,indent=2),encoding='utf-8')
    (WORK/'candidate-pairs.json').write_text(json.dumps(pairs,ensure_ascii=False,indent=2),encoding='utf-8')
    from collections import Counter
    print(json.dumps({'models':len(results),'accepted_models':len(pairs),'pairs':sum(len(r['backdrops']) for r in pairs),'families':dict(Counter(r['family'] for r in pairs)),'reasons':dict(Counter(r['reason'] for r in results))}),flush=True)
