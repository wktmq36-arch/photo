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


def tonal_palette(source, source_mask, reference, reference_mask):
    """Map the brightness ranks of the selection to the reference's color ramp."""
    histogram = source.convert('L').histogram(mask=source_mask)
    bounds = reference_mask.getbbox()
    reference = reference.crop(bounds).convert('RGB')
    mask = reference_mask.crop(bounds)
    counts = [0] * 256
    sums = [[0, 0, 0] for _ in counts]
    for tone, rgb, selected in zip(reference.convert('L').getdata(), reference.getdata(), mask.getdata()):
        if selected:
            counts[tone] += 1
            for channel, value in enumerate(rgb):
                sums[tone][channel] += value

    total = sum(counts)
    stops = []
    cumulative = 0
    for count, channels in zip(counts, sums):
        if count:
            stops.append(((cumulative + count / 2) / total, [value / count for value in channels]))
            cumulative += count

    palette = [[], [], []]
    source_total = sum(histogram)
    cumulative = 0
    index = 0
    for count in histogram:
        rank = (cumulative + count / 2) / source_total
        cumulative += count
        while index + 1 < len(stops) and stops[index + 1][0] <= rank:
            index += 1
        low_rank, low = stops[index]
        high_rank, high = stops[min(index + 1, len(stops) - 1)]
        weight = max(0, (rank - low_rank) / (high_rank - low_rank)) if high_rank > low_rank else 0
        for channel in range(3):
            palette[channel].append(round(low[channel] + (high[channel] - low[channel]) * weight))
    return palette


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
        depth = edit.get('clone_depth', 0)
        if type(depth) is not int or depth < 0:
            raise ValueError('Invalid color adjustment order')
        if 'palette' in edit:
            palette = edit['palette']
            if (not isinstance(palette, list) or len(palette) != 3
                    or any(not isinstance(channel, list) or len(channel) != 256
                           or any(type(value) is not int or not 0 <= value <= 255 for value in channel)
                           for channel in palette)):
                raise ValueError('Invalid tonal palette')
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
        colors = patch
        if 'palette' in edit:
            tone = patch.convert('L')
            colors = Image.merge('RGB', tuple(tone.point(channel) for channel in edit['palette']))
        hue, sat, value = colors.convert('HSV').split()
        hue_shift = round(edit['hue'] * 256 / 360)
        hue = hue.point(lambda v: (v + hue_shift) % 256)
        def shift(channel, amount):
            ratio = amount / 100
            return channel.point(lambda v: round(v + (255 - v if ratio >= 0 else v) * ratio))
        sat = shift(sat, edit['saturation'])
        value = shift(value, edit['value'])
        if any(edit[key] for key in ('hue', 'saturation', 'value')):
            adjusted = Image.merge('HSV', (hue, sat, value)).convert('RGBA')
        else:
            adjusted = colors.convert('RGBA')
        adjusted.putalpha(patch.getchannel('A'))
        mask = None
        if 'mask' in edit:
            with Image.open(io.BytesIO(base64.b64decode(edit['mask']))) as source:
                mask = source.resize(patch.size, Image.Resampling.BILINEAR)
        result.paste(adjusted, box, mask)
    return result
