"""Portable, non-destructive panel layouts. Assets contain only flattened pixels."""
import base64
import hashlib
import io
import math
from PIL import Image,ImageDraw


def pixel_asset(image):
    clean=Image.frombytes('RGBA',image.size,image.convert('RGBA').tobytes())
    stream=io.BytesIO();clean.save(stream,'PNG')
    data=stream.getvalue()
    return hashlib.sha256(data).hexdigest(),base64.b64encode(data).decode('ascii')


def paired_asset(image,uncensored):
    key,data=pixel_asset(image);other_key,other_data=pixel_asset(uncensored)
    # A censored image can be identical while its uncensored counterpart differs.
    return hashlib.sha256((key+other_key).encode('ascii')).hexdigest(),data,other_data


def decode_asset(data):
    with Image.open(io.BytesIO(base64.b64decode(data,validate=True))) as source:
        return source.convert('RGBA').copy()


def empty_composition():
    return {'assets':{},'cells':[{'rect':[0.,0.,1.,1.]}]}


def validate_composition(value,check_images=False):
    if not isinstance(value,dict) or not isinstance(value.get('assets'),dict) or not isinstance(value.get('cells'),list):
        raise ValueError('잘못된 컷 편집 데이터')
    def numbers(values,count):
        return isinstance(values,list) and len(values)==count and all(isinstance(v,(int,float)) and math.isfinite(v) for v in values)
    if not 0<=len(value['cells'])<=1024:raise ValueError('컷 개수는 최대 1024개입니다.')
    if not isinstance(value.get('freeform',False),bool):raise ValueError('잘못된 컷 배치 방식')
    gutter=value.get('gutter',0.)
    if not isinstance(gutter,(int,float)) or not math.isfinite(gutter) or not 0<=gutter<=.1:raise ValueError('잘못된 컷 간격')
    for key,data in value['assets'].items():
        if not isinstance(key,str) or not isinstance(data,str):raise ValueError('잘못된 컷 이미지')
        if check_images:decode_asset(data)
    variants=value.get('uncensored_assets',{})
    if not isinstance(variants,dict):raise ValueError('잘못된 원본용 컷 이미지')
    for key,data in variants.items():
        if key not in value['assets'] or not isinstance(data,str):raise ValueError('잘못된 원본용 컷 이미지')
        if check_images and decode_asset(data).size!=decode_asset(value['assets'][key]).size:raise ValueError('원본용 컷 이미지 크기 불일치')
    lines=value.get('lines',[])
    if not isinstance(lines,list) or len(lines)>10000:raise ValueError('잘못된 검은선 데이터')
    for line in lines:
        if not isinstance(line,dict) or not isinstance(line.get('points'),list) or not line['points'] or len(line['points'])>100000:raise ValueError('잘못된 검은선 좌표')
        if any(not numbers(point,2) or any(v<0 or v>1 for v in point) for point in line['points']):raise ValueError('잘못된 검은선 좌표')
        width=line.get('width',0)
        if not isinstance(width,(int,float)) or not math.isfinite(width) or not 0<width<=.2:raise ValueError('잘못된 검은선 굵기')
    for cell in value['cells']:
        if not isinstance(cell,dict):raise ValueError('잘못된 컷 데이터')
        rect=cell.get('rect')
        if not numbers(rect,4) or not (0<=rect[0]<rect[2]<=1 and 0<=rect[1]<rect[3]<=1):raise ValueError('잘못된 컷 범위')
        border=cell.get('border',0.)
        if not isinstance(border,(int,float)) or not math.isfinite(border) or not 0<=border<=.1:raise ValueError('잘못된 컷 테두리 두께')
        if not isinstance(cell.get('stretch',False),bool):raise ValueError('잘못된 이미지 맞춤 방식')
        if 'asset' in cell:
            if cell['asset'] not in value['assets']:raise ValueError('컷 이미지 누락')
            scale=cell.get('scale',1.)
            if not isinstance(scale,(int,float)) or not math.isfinite(scale) or not .05<=scale<=32:raise ValueError('잘못된 컷 배율')
            if not numbers(cell.get('offset',[0.,0.]),2) or any(abs(v)>100 for v in cell.get('offset',[0.,0.])):raise ValueError('잘못된 컷 위치')


def panel_border(image,box,border,inset=0):
    if not border:return
    left,top,right,bottom=box
    rect=(left+inset,top+inset,right-inset-1,bottom-inset-1)
    if rect[2]>=rect[0] and rect[3]>=rect[1]:ImageDraw.Draw(image).rectangle(rect,outline='black',width=border)


def render_composition(image,composition,cache=None,include_mosaic=True):
    if not composition:return image
    result=image.convert('RGBA').copy();width,height=result.size
    cache={} if cache is None else cache
    for cell in composition['cells']:
        key=cell.get('asset')
        if not key:
            box=tuple(round(v*(width if i%2==0 else height)) for i,v in enumerate(cell['rect']))
            gap=round(composition.get('gutter',0.)*width)
            if composition.get('freeform') and composition.get('gutter'):
                box=tuple(round(v*(width if i%2==0 else height)) for i,v in enumerate(cell['rect']))
                gap=round(composition['gutter']*width)
                if gap:ImageDraw.Draw(result).rectangle((box[0],box[1],max(box[0],box[2]-1),max(box[1],box[3]-1)),outline='white',width=gap)
            panel_border(result,box,round(cell.get('border',0.)*width),gap if composition.get('freeform') else (gap+1)//2)
            continue
        variant=not include_mosaic and key in composition.get('uncensored_assets',{})
        cache_key=(key,'uncensored') if variant else key
        if cache_key not in cache:cache[cache_key]=decode_asset(composition['uncensored_assets'][key] if variant else composition['assets'][key])
        source=cache[cache_key];x1,y1,x2,y2=cell['rect']
        box=(round(x1*width),round(y1*height),round(x2*width),round(y2*height))
        cw,ch=box[2]-box[0],box[3]-box[1]
        if cw<=0 or ch<=0:continue
        ratio=max(cw/source.width,ch/source.height)*cell.get('scale',1.)
        ratio_x=cw/source.width*cell.get('scale',1.) if cell.get('stretch') else ratio
        ratio_y=ch/source.height*cell.get('scale',1.) if cell.get('stretch') else ratio
        ox,oy=cell.get('offset',[0.,0.])
        left=(cw-source.width*ratio_x)/2+ox*cw;top=(ch-source.height*ratio_y)/2+oy*ch
        # Inverse mapping renders only the clipped cell, even at high zoom.
        patch=source.transform((cw,ch),Image.Transform.AFFINE,(1/ratio_x,0,-left/ratio_x,0,1/ratio_y,-top/ratio_y),Image.Resampling.BICUBIC)
        background=Image.new('RGBA',(cw,ch),'white');background.alpha_composite(patch)
        if composition.get('freeform'):
            gap=round(composition.get('gutter',0.)*width)
            if gap:ImageDraw.Draw(background).rectangle((0,0,cw-1,ch-1),outline='white',width=gap)
        gap=round(composition.get('gutter',0.)*width)
        panel_border(background,(0,0,cw,ch),round(cell.get('border',0.)*width),gap if composition.get('freeform') else (gap+1)//2)
        result.paste(background,box)
    gap=round(composition.get('gutter',0.)*width)
    if gap and not composition.get('freeform'):
        draw=ImageDraw.Draw(result)
        for cell in composition['cells']:
            x1,y1,x2,y2=cell['rect'];left,top,right,bottom=round(x1*width),round(y1*height),round(x2*width),round(y2*height)
            if x1>0:draw.line((left,top,left,bottom),fill='white',width=gap)
            if x2<1:draw.line((right,top,right,bottom),fill='white',width=gap)
            if y1>0:draw.line((left,top,right,top),fill='white',width=gap)
            if y2<1:draw.line((left,bottom,right,bottom),fill='white',width=gap)
    draw=ImageDraw.Draw(result)
    for line in composition.get('lines',[]):
        points=[(round(x*(width-1)),round(y*(height-1))) for x,y in line['points']]
        thickness=max(1,round(line['width']*width));radius=(thickness-1)/2
        if len(points)>1:draw.line(points,fill='black',width=thickness,joint='curve')
        for x,y in (points[0],points[-1]):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='black')
    return result
