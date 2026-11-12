import base64
import io
import math

from PIL import Image, ImageChops, ImageDraw


def wand_mask(image, seed, tolerance):
    rgb = image.convert('RGB')
    diff = ImageChops.difference(rgb, Image.new('RGB', rgb.size, rgb.getpixel(seed)))
    r, g, b = diff.split()
    similar = ImageChops.lighter(ImageChops.lighter(r, g), b).point(
        lambda value: 255 if value <= tolerance else 0
    )
    ImageDraw.floodfill(similar, seed, 128)
    return similar.point(lambda value: 255 if value == 128 else 0)


def encode_mask(mask):
    stream = io.BytesIO()
    mask.save(stream, 'PNG')
    return base64.b64encode(stream.getvalue()).decode('ascii')


def validate_colors(edits):
    if not isinstance(edits, list) or len(edits) > 1024:
        raise ValueError('Invalid color adjustments')
    for edit in edits:
        if not isinstance(edit, dict):
            raise ValueError('Invalid color adjustment')
        rect = edit.get('rect')
        if (not isinstance(rect, list) or len(rect) != 4
                or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect)
                or not (0 <= rect[0] < rect[2] <= 1 and 0 <= rect[1] < rect[3] <= 1)):
            raise ValueError('Invalid color selection')
        for key, limit in [('hue', 180), ('saturation', 100), ('value', 100)]:
            if type(edit.get(key)) is not int or abs(edit[key]) > limit:
                raise ValueError('Invalid color adjustment')
        if 'mask' in edit:
            with Image.open(io.BytesIO(base64.b64decode(edit['mask'], validate=True)), formats=['PNG']) as mask:
                if mask.mode != 'L' or max(mask.size) > 1600:
                    raise ValueError('Invalid selection mask')
                mask.load()


def render_colors(image, edits):
    if not edits:
        return image
    from imaging import crop_box
    result = image.copy()
    for edit in edits:
        box = crop_box(result, edit['rect'])
        patch = result.crop(box).convert('RGBA')
        hue, sat, value = patch.convert('HSV').split()
        hue_shift = round(edit['hue'] * 256 / 360)
        hue = hue.point(lambda v: (v + hue_shift) % 256)
        def shift(channel, amount):
            ratio = amount / 100
            return channel.point(lambda v: round(v + (255 - v if ratio >= 0 else v) * ratio))
        sat = shift(sat, edit['saturation'])
        value = shift(value, edit['value'])
        adjusted = Image.merge('HSV', (hue, sat, value)).convert('RGBA')
        adjusted.putalpha(patch.getchannel('A'))
        mask = None
        if 'mask' in edit:
            with Image.open(io.BytesIO(base64.b64decode(edit['mask']))) as source:
                mask = source.resize(patch.size, Image.Resampling.BILINEAR)
        result.paste(adjusted, box, mask)
    return result
