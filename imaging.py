from PIL import Image, ImageOps
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
        result.paste(small.resize(crop.size, Image.Resampling.NEAREST), box)
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
