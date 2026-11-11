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
        if line.get('cap','round') not in ('round','flat'):raise ValueError('잘못된 검은선 끝 모양')
        width=line.get('width',0)
        if not isinstance(width,(int,float)) or not math.isfinite(width) or not 0<width<=.2:raise ValueError('잘못된 검은선 굵기')
    for cell in value['cells']:
        if not isinstance(cell,dict):raise ValueError('잘못된 컷 데이터')
        rect=cell.get('rect')
        if not numbers(rect,4) or not (0<=rect[0]<rect[2]<=1 and 0<=rect[1]<rect[3]<=1):raise ValueError('잘못된 컷 범위')
        if not isinstance(cell.get('clone_depth',0),int) or not 0<=cell.get('clone_depth',0)<=1000000:raise ValueError('잘못된 컷 도장 순서')
        polygon=cell.get('polygon')
        if polygon is not None and (not isinstance(polygon,list) or not 3<=len(polygon)<=128 or any(not numbers(point,2) or any(v<0 or v>1 for v in point) for point in polygon)):
            raise ValueError('잘못된 자유형 컷 좌표')
        sides=cell.get('border_sides',['top','bottom','left','right'])
        if not isinstance(sides,list) or any(side not in ('top','bottom','left','right') for side in sides) or len(set(sides))!=len(sides):raise ValueError('잘못된 컷 테두리 방향')
        border=cell.get('border',0.)
        if not isinstance(border,(int,float)) or not math.isfinite(border) or not 0<=border<=.1:raise ValueError('잘못된 컷 테두리 두께')
        if not isinstance(cell.get('stretch',False),bool):raise ValueError('잘못된 이미지 맞춤 방식')
        if 'asset' in cell:
            if cell['asset'] not in value['assets']:raise ValueError('컷 이미지 누락')
            scale=cell.get('scale',1.)
            if not isinstance(scale,(int,float)) or not math.isfinite(scale) or not .05<=scale<=32:raise ValueError('잘못된 컷 배율')
            if not numbers(cell.get('offset',[0.,0.]),2) or any(abs(v)>100 for v in cell.get('offset',[0.,0.])):raise ValueError('잘못된 컷 위치')


def panel_border(image,box,border,inset=0,sides=None):
    if not border:return
    left,top,right,bottom=box
    rect=(left+inset,top+inset,right-inset-1,bottom-inset-1)
    if rect[2]<rect[0] or rect[3]<rect[1]:return
    draw=ImageDraw.Draw(image);left,top,right,bottom=rect
    sides=['top','bottom','left','right'] if sides is None else sides
    areas={'top':(left,top,right,min(bottom,top+border-1)), 'bottom':(left,max(top,bottom-border+1),right,bottom),
           'left':(left,top,min(right,left+border-1),bottom), 'right':(max(left,right-border+1),top,right,bottom)}
    for side in sides:draw.rectangle(areas[side],fill='black')


def smooth_black_line(image, points, width, round_caps=False):
    # Rasterize only the stroke's bounds at higher resolution.
    padding = width + 2
    left = max(0, math.floor(min(x for x, y in points)) - padding)
    top = max(0, math.floor(min(y for x, y in points)) - padding)
    right = min(image.width, math.ceil(max(x for x, y in points)) + padding)
    bottom = min(image.height, math.ceil(max(y for x, y in points)) + padding)
    if right <= left or bottom <= top:
        return
    scale = 4
    size = (right - left, bottom - top)
    mask = Image.new('L', (size[0] * scale, size[1] * scale))
    coordinates = [(round((x - left) * scale + 1.5), round((y - top) * scale + 1.5)) for x, y in points]
    draw = ImageDraw.Draw(mask)
    draw.line(coordinates, fill=255, width=width * scale, joint='curve')
    if round_caps:
        radius = (width * scale - 1) / 2
        for x, y in (coordinates[0], coordinates[-1]):
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    image.paste((0, 0, 0, 255), (left, top, right, bottom), mask.resize(size, Image.Resampling.BOX))


def polygon_border(image,points,border,sides=None,shape=None):
    if not border:return
    sides=set(['top','bottom','left','right'] if sides is None else sides)
    shape=points if shape is None else shape
    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(shape,shape[1:]+shape[:1]))
    winding=1 if area>=0 else -1
    draw=ImageDraw.Draw(image)
    for index,(a,b) in enumerate(zip(shape,shape[1:]+shape[:1])):
        dx,dy=(b[0]-a[0])*winding,(b[1]-a[1])*winding
        if dx==dy==0:continue
        side=('top' if dx>0 else 'bottom') if abs(dx)>=abs(dy) else ('right' if dy>0 else 'left')
        if side in sides:
            edge = [points[index], points[(index + 1) % len(points)]]
            if dx and dy:
                smooth_black_line(image, edge, border)
            else:
                draw.line(edge, fill='black', width=border)


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
            if cell.get('polygon'):
                left,top,right,bottom=box
                points=[(round(left+x*(right-left-1)),round(top+y*(bottom-top-1))) for x,y in cell['polygon']]
                border=round(cell.get('border',0.)*width)
                polygon_border(result,points,border,cell.get('border_sides'),cell['polygon'])
            else:
                panel_border(result,box,round(cell.get('border',0.)*width),gap if composition.get('freeform') else (gap+1)//2,cell.get('border_sides'))
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
        panel_border(background,(0,0,cw,ch),round(cell.get('border',0.)*width),gap if composition.get('freeform') else (gap+1)//2,cell.get('border_sides'))
        if cell.get('polygon'):
            precise_points = [(x * (cw - 1), y * (ch - 1)) for x, y in cell['polygon']]
            points = [(round(x), round(y)) for x, y in precise_points]
            scale = 4
            mask = Image.new('L', (cw * scale, ch * scale))
            ImageDraw.Draw(mask).polygon(
                [(round(x * scale + 1.5), round(y * scale + 1.5)) for x, y in precise_points],
                fill=255,
            )
            mask = mask.resize((cw, ch), Image.Resampling.BOX)
            # Keep edges that coincide with the cut's rectangular bounds opaque.
            for a, b in zip(points, points[1:] + points[:1]):
                if (a[0] == b[0] and a[0] in (0, cw - 1)) or (a[1] == b[1] and a[1] in (0, ch - 1)):
                    ImageDraw.Draw(mask).line((a, b), fill=255)
            # Polygon borders follow the actual outline, rather than its bounding box.
            background=Image.new('RGBA',(cw,ch),'white');background.alpha_composite(patch)
            gap=round(composition.get('gutter',0.)*width)
            if gap:ImageDraw.Draw(background).line(points+[points[0]],fill='white',width=gap*2,joint='curve')
            border=round(cell.get('border',0.)*width)
            polygon_border(background,points,border*2,cell.get('border_sides'),cell['polygon'])
            result.paste(background,box,mask)
        else:result.paste(background,box)
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
        if len(points)>1 and not (all(x==points[0][0] for x,y in points) or all(y==points[0][1] for x,y in points)):
            precise_points = [(x*(width-1), y*(height-1)) for x,y in line['points']]
            smooth_black_line(result, precise_points, thickness, line.get('cap','round')=='round')
            continue
        if len(points)>1:draw.line(points,fill='black',width=thickness,joint='curve')
        if line.get('cap','round')=='round':
            for x,y in (points[0],points[-1]):draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill='black')
        elif len(points)==1:
            x,y=points[0];left,top=x-thickness//2,y-thickness//2;draw.rectangle((left,top,left+thickness-1,top+thickness-1),fill='black')
    return result
