from PIL import Image, ImageOps, ImageDraw
from pathlib import Path
import math

EXTENSIONS = {'.webp', '.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}

def read_pixels(path):
    with Image.open(path) as source:
        source.seek(0)
        oriented = ImageOps.exif_transpose(source)
        rgba = oriented.convert('RGBA')
        # Construct from pixel bytes: no EXIF, XMP, ICC, comments or source info.
        return Image.frombytes('RGBA', rgba.size, rgba.tobytes())

def render_regions(image, regions):
    result = image.copy()
    width, height = result.size
    for region in regions:
        x1, y1, x2, y2 = region['rect']
        box = (max(0, math.floor(x1 * width)), max(0, math.floor(y1 * height)),
               min(width, math.ceil(x2 * width)), min(height, math.ceil(y2 * height)))
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        crop = result.crop(box)
        block = max(2, round(region['strength'] * width / 1000))
        small = crop.resize((max(1, crop.width // block), max(1, crop.height // block)), Image.Resampling.BOX)
        mosaic = small.resize(crop.size, Image.Resampling.NEAREST)
        mask = None
        if region.get('kind') == 'brush':
            mask = Image.new('L', crop.size, 0)
            draw = ImageDraw.Draw(mask)
            radius = region['radius'] * width
            points = [(x*width-box[0], y*height-box[1]) for x,y in region['points']]
            if len(points)>1: draw.line(points, fill=255, width=max(1,round(radius*2)))
            for x,y in points: draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
        result.paste(mosaic, box, mask)
    return result

def export_image(entry, destination, fmt):
    result = render_regions(read_pixels(entry['path']), entry['regions'])
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

def export_pair(entry, index, destination, fmt, stem):
    destination=Path(destination)
    censored=destination/(stem+'_cen'); original=destination/(stem+'_uncen')
    censored.mkdir(exist_ok=True); original.mkdir(exist_ok=True)
    number=f'{index:03d}'
    ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
    processed=censored/(number+'.'+ext)
    source=Path(entry['path']); unprocessed=original/(number+source.suffix)
    try:
        strip_metadata(source,unprocessed)
        export_image(entry,processed,fmt)
    except Exception:
        # Do not leave a misleading partial pair if either side fails.
        processed.unlink(missing_ok=True);unprocessed.unlink(missing_ok=True)
        raise
