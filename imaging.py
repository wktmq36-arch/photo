from PIL import Image, ImageOps, ImageDraw, ImageFilter, ImageChops
from pathlib import Path
import math
from composition import render_composition

EXTENSIONS = {'.webp', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}

def read_pixels(path):
    with Image.open(path) as source:
        source.seek(0)
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert('RGBA')
        # Construct from pixel bytes: no EXIF, XMP, ICC, comments or source info.
        return Image.frombytes('RGBA', rgba.size, rgba.tobytes())

def grid_mosaic(image, box, block):
    """Sample original pixels on a grid anchored to the image, not the stroke."""
    left,top=(box[0]//block)*block,(box[1]//block)*block
    right,bottom=math.ceil(box[2]/block)*block,math.ceil(box[3]/block)*block
    crop=image.crop((left,top,min(right,image.width),min(bottom,image.height)))
    # Extend edge pixels for partial cells; never average in black crop padding.
    padded=Image.new(image.mode,(right-left,bottom-top));padded.paste(crop,(0,0))
    if crop.width<padded.width:
        padded.paste(crop.crop((crop.width-1,0,crop.width,crop.height)).resize((padded.width-crop.width,crop.height)),(crop.width,0))
    if crop.height<padded.height:
        padded.paste(padded.crop((0,crop.height-1,padded.width,crop.height)).resize((padded.width,padded.height-crop.height)),(0,crop.height))
    small=padded.resize((padded.width//block,padded.height//block),Image.Resampling.BOX)
    mosaic=small.resize(padded.size,Image.Resampling.NEAREST)
    return mosaic.crop((box[0]-left,box[1]-top,box[2]-left,box[3]-top))

def render_regions(image, regions):
    result=image.copy();width,height=image.size;groups={}
    for region in regions:
        brush=region.get('kind')=='brush'
        if brush:
            points=region['points']
            if not points:continue
            radius=region['radius']*width
            xs=[p[0]*width for p in points];ys=[p[1]*height for p in points]
            # A narrow outward feather leaves the entire existing mask opaque.
            box=(max(0,math.floor(min(xs)-radius)-3),max(0,math.floor(min(ys)-radius)-3),
                 min(width,math.ceil(max(xs)+radius)+4),min(height,math.ceil(max(ys)+radius)+4))
        else:
            x1,y1,x2,y2=region['rect']
            box=(max(0,math.floor(x1*width)),max(0,math.floor(y1*height)),min(width,math.ceil(x2*width)),min(height,math.ceil(y2*height)))
        if box[2]<=box[0] or box[3]<=box[1]:continue
        block=max(2,round(region['strength']*width/1000))
        groups.setdefault(block,[]).append((region,box))
    # Combine masks BEFORE compositing. Repeated strokes are idempotent and the
    # strongest block wins overlaps regardless of the order the strokes were made.
    for block,items in sorted(groups.items()):
        box=(min(b[0] for r,b in items),min(b[1] for r,b in items),max(b[2] for r,b in items),max(b[3] for r,b in items))
        mask=Image.new('L',(box[2]-box[0],box[3]-box[1]),0)
        for region,bounds in items:
            if region.get('kind')=='brush':
                local=Image.new('L',(bounds[2]-bounds[0],bounds[3]-bounds[1]),0);draw=ImageDraw.Draw(local)
                radius=region['radius']*width
                points=[(x*width-bounds[0],y*height-bounds[1]) for x,y in region['points']]
                if len(points)>1:draw.line(points,fill=255,width=max(1,round(radius*2)))
                for x,y in points:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
            else:local=Image.new('L',(bounds[2]-bounds[0],bounds[3]-bounds[1]),255)
            offset=(bounds[0]-box[0],bounds[1]-box[1]);area=(*offset,offset[0]+local.width,offset[1]+local.height)
            mask.paste(ImageChops.lighter(mask.crop(area),local),offset)
        # Feather the union, so internal stroke seams cannot become visible.
        if any(r.get('kind')=='brush' for r,b in items):
            mask=ImageChops.lighter(mask,mask.filter(ImageFilter.GaussianBlur(.65)))
        result.paste(grid_mosaic(image,box,block),box,mask)
    return result

def clone_bounds(points,radius,sigma,size):
    pad=math.ceil(radius+sigma*4+3)
    return (max(0,math.floor(min(x for x,y in points))-pad),
            max(0,math.floor(min(y for x,y in points))-pad),
            min(size[0],math.ceil(max(x for x,y in points))+pad+1),
            min(size[1],math.ceil(max(y for x,y in points))+pad+1))

def draw_clone_mask(mask,points,radius,origin=(0,0)):
    draw=ImageDraw.Draw(mask)
    line=[(math.floor(x)-origin[0],math.floor(y)-origin[1]) for x,y in points]
    for first,second in zip(line,line[1:]):draw.line([first,second],fill=255,width=max(1,round(radius*2)))
    for x,y in points:
        draw.ellipse((math.floor(x-radius)-origin[0],math.floor(y-radius)-origin[1],
                      math.floor(x+radius)-origin[0],math.floor(y+radius)-origin[1]),fill=255)

def clone_patch(base,mask,box,dx,dy,sigma):
    if sigma>0:mask=mask.filter(ImageFilter.GaussianBlur(sigma))
    valid=Image.new('L',mask.size,0)
    left,top=max(box[0],dx),max(box[1],dy)
    right,bottom=min(box[2],base.width+dx),min(box[3],base.height+dy)
    if left<right and top<bottom:
        ImageDraw.Draw(valid).rectangle((left-box[0],top-box[1],right-box[0]-1,bottom-box[1]-1),fill=255)
    shifted=base.crop((box[0]-dx,box[1]-dy,box[2]-dx,box[3]-dy))
    return Image.composite(shifted,base.crop(box),ImageChops.multiply(mask,valid))

def render_clones(image, strokes):
    if not strokes:return image
    result=image.copy();width,height=image.size
    for stroke in strokes:
        points=[(x*width,y*height) for x,y in stroke['points']]
        if not points:continue
        radius=max(1,stroke['radius']*width);sigma=radius*stroke.get('softness',.5)*.45
        box=clone_bounds(points,radius,sigma,image.size)
        mask=Image.new('L',(box[2]-box[0],box[3]-box[1]),0)
        draw_clone_mask(mask,points,radius,box[:2])
        dx=round((stroke['points'][0][0]-stroke['source'][0])*width);dy=round((stroke['points'][0][1]-stroke['source'][1])*height)
        result.paste(clone_patch(result,mask,box,dx,dy,sigma),box)
    return result

class ClonePreview:
    """Incremental current-stroke preview; its source stays fixed during a stroke."""
    def __init__(self,base,stroke):
        self.base=base;self.result=base.copy();self.stroke=stroke
        self.mask=Image.new('L',base.size,0);self.count=0
        self.radius=max(1,stroke['radius']*base.width)
        self.sigma=self.radius*stroke.get('softness',.5)*.45
        first=stroke['points'][0]
        self.dx=round((first[0]-stroke['source'][0])*base.width)
        self.dy=round((first[1]-stroke['source'][1])*base.height)
    def update(self,points):
        if len(points)<=self.count:return self.result
        tail=points[max(0,self.count-1):]
        pixels=[(x*self.base.width,y*self.base.height) for x,y in tail]
        draw_clone_mask(self.mask,pixels,self.radius)
        box=clone_bounds(pixels,self.radius,self.sigma,self.base.size)
        if self.sigma>0:
            # Blur with a surrounding margin, then update only the interior.
            # Otherwise crop-edge padding would change previously painted pixels.
            margin=math.ceil(self.sigma*4+3)
            outer=(max(0,box[0]-margin),max(0,box[1]-margin),min(self.base.width,box[2]+margin),min(self.base.height,box[3]+margin))
            blurred=self.mask.crop(outer).filter(ImageFilter.GaussianBlur(self.sigma))
            local=blurred.crop((box[0]-outer[0],box[1]-outer[1],box[2]-outer[0],box[3]-outer[1]))
        else:local=self.mask.crop(box)
        patch=clone_patch(self.base,local,box,self.dx,self.dy,0)
        self.result.paste(patch,box);self.count=len(points)
        return self.result

def render_entry(image,entry):
    # Retouch first; censor last, so a clone can never undo a mosaic.
    composed=render_composition(image,entry.get('composition'))
    cloned=render_clones(composed,entry.get('clones',[]))
    return render_regions(cloned,entry['regions']) if entry['regions'] else cloned

def export_image(entry, destination, fmt):
    result = render_entry(read_pixels(entry['path']), entry)
    clean = Image.frombytes('RGBA', result.size, result.tobytes())
    if fmt == 'JPEG':
        background = Image.new('RGB', clean.size, 'white')
        background.paste(clean, mask=clean.getchannel('A'))
        background.save(destination, 'JPEG', quality=95, subsampling=0)
    elif fmt == 'WEBP':
        clean.save(destination, 'WEBP', lossless=True)
    else:
        clean.save(destination, 'PNG')
    with Image.open(destination) as check:
        forbidden = set(check.info) & {'exif', 'xmp', 'XML:com.adobe.xmp', 'icc_profile', 'comment', 'Comment', 'parameters', 'prompt', 'workflow'}
        if check.getexif() or forbidden:
            raise RuntimeError(f'메타데이터 검증 실패: {Path(destination).name}')


def strip_metadata(source, destination):
    """Strip WebP/PNG/JPEG metadata without decoding or recompressing pixels."""
    import struct
    source=Path(source); destination=Path(destination)
    data=source.read_bytes()
    if data[:4]==b'RIFF' and data[8:12]==b'WEBP':
        if len(data)<12 or struct.unpack('<I',data[4:8])[0]+8!=len(data):
            raise ValueError('잘못된 WebP 파일 크기')
        chunks=[];offset=12
        while offset<len(data):
            if offset+8>len(data):raise ValueError('손상된 WebP 청크')
            kind=data[offset:offset+4];size=struct.unpack('<I',data[offset+4:offset+8])[0]
            end=offset+8+size+(size%2)
            if end>len(data):raise ValueError('손상된 WebP 데이터')
            payload=data[offset+8:offset+8+size]
            # Keep only documented image/animation chunks; discard unknown metadata.
            if kind in {b'VP8X',b'VP8 ',b'VP8L',b'ALPH',b'ANIM',b'ANMF'}:
                if kind==b'VP8X':
                    if len(payload)!=10:raise ValueError('손상된 WebP 헤더')
                    payload=bytes([payload[0]&~(0x20|0x08|0x04)])+payload[1:]
                chunks.append(kind+struct.pack('<I',len(payload))+payload+(b'\0' if len(payload)%2 else b''))
            offset=end
        body=b'WEBP'+b''.join(chunks)
        clean=b'RIFF'+struct.pack('<I',len(body))+body
    elif data.startswith(b'\x89PNG\r\n\x1a\n'):
        clean=data[:8];offset=8
        while offset<len(data):
            if offset+12>len(data):raise ValueError('손상된 PNG 청크')
            size=struct.unpack('>I',data[offset:offset+4])[0];kind=data[offset+4:offset+8];end=offset+12+size
            if end>len(data):raise ValueError('손상된 PNG 데이터')
            if kind in {b'IHDR',b'PLTE',b'IDAT',b'IEND',b'tRNS',b'acTL',b'fcTL',b'fdAT'}:clean+=data[offset:end]
            offset=end
            if kind==b'IEND':break
    elif data.startswith(b'\xff\xd8'):
        clean=data[:2];offset=2
        while offset<len(data):
            if data[offset]!=255:raise ValueError('손상된 JPEG 마커')
            start=offset
            while offset<len(data) and data[offset]==255:offset+=1
            if offset>=len(data):raise ValueError('손상된 JPEG 헤더')
            marker=data[offset];offset+=1
            if marker==0xDA:
                if offset+2>len(data):raise ValueError('손상된 JPEG 스캔')
                size=struct.unpack('>H',data[offset:offset+2])[0]
                if size<2 or offset+size>len(data):raise ValueError('손상된 JPEG 스캔 헤더')
                offset+=size;scan_start=offset
                while offset<len(data):
                    if data[offset]!=255:offset+=1;continue
                    candidate=offset;offset+=1
                    while offset<len(data) and data[offset]==255:offset+=1
                    if offset>=len(data):raise ValueError('손상된 JPEG 스캔 데이터')
                    if data[offset]==0 or 0xD0<=data[offset]<=0xD7:offset+=1;continue
                    offset=candidate;break
                clean+=data[start:offset];continue
            if marker==0xD9:clean+=data[start:offset];break
            if marker==0x01 or 0xD0<=marker<=0xD7:clean+=data[start:offset];continue
            if offset+2>len(data):raise ValueError('손상된 JPEG 세그먼트')
            size=struct.unpack('>H',data[offset:offset+2])[0];end=offset+size
            if size<2 or end>len(data):raise ValueError('손상된 JPEG 데이터')
            if not (0xE0<=marker<=0xEF or marker==0xFE):clean+=data[start:end]
            offset=end
    elif source.suffix.lower() in {'.bmp','.tif','.tiff'}:
        pixels=read_pixels(source)
        pixels.save(destination,format='BMP' if source.suffix.lower()=='.bmp' else 'TIFF')
        return
    else:
        raise ValueError('지원하지 않는 이미지 형식입니다.')
    destination.write_bytes(clean)
    with Image.open(destination) as check:
        if check.getexif() or set(check.info)&{'exif','xmp','XML:com.adobe.xmp','icc_profile','comment','Comment','parameters','prompt','workflow'}:
            raise RuntimeError('원본 메타데이터 제거 검증 실패')

def export_pair(entry, index, destination, fmt, stem, outputs=None, main_index=None):
    outputs=outputs or {'cen':True,'uncen':True,'main':True}
    destination=Path(destination);number=f'{index:03d}'
    ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
    created=[]
    def target(kind,suffix,number_override=None):
        folder=destination/(stem+'_'+kind);folder.mkdir(exist_ok=True)
        path=folder/((number_override or number)+suffix);created.append(path);return path
    try:
        if outputs.get('uncen'):
            strip_metadata(entry['path'],target('uncen',Path(entry['path']).suffix))
        processed=None
        if outputs.get('cen'):
            processed=target('cen','.'+ext);export_image(entry,processed,fmt)
        if outputs.get('main') and entry.get('main_selected',False):
            main_output=target('main','.'+ext,f'{main_index if main_index is not None else index:03d}')
            if processed is not None:
                import shutil
                shutil.copyfile(processed,main_output)
            else:export_image(entry,main_output,fmt)
    except Exception:
        for path in created:path.unlink(missing_ok=True)
        raise
    return [str(path) for path in created]
