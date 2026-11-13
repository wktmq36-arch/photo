from PIL import Image, ImageDraw


def render_moves(image, moves):
    if not moves:
        return image
    from imaging import crop_box
    result = image.convert('RGBA').copy()
    for move in moves:
        box = crop_box(result, move['rect'])
        patch = result.crop(box)
        mask = Image.new('L', patch.size, 255)
        if move['outline']:
            scale = 2
            mask = Image.new('L', (patch.width * scale, patch.height * scale))
            points = [(round((x * result.width - box[0]) * scale),
                       round((y * result.height - box[1]) * scale)) for x, y in move['outline']]
            ImageDraw.Draw(mask).polygon(points, fill=255)
            mask = mask.resize(patch.size, Image.Resampling.BOX)
        from PIL import ImageChops
        patch.putalpha(ImageChops.multiply(patch.getchannel('A'), mask))
        result.paste((255, 255, 255, 255), box, mask)
        scale = move['scale'] / 100
        size = (max(1, round(patch.width * scale)), max(1, round(patch.height * scale)))
        position = (round((box[0] + box[2] - size[0]) / 2 + move['offset'][0] * result.width),
                    round((box[1] + box[3] - size[1]) / 2 + move['offset'][1] * result.height))
        result.alpha_composite(patch.resize(size, Image.Resampling.LANCZOS), position)
    return result


def validate_moves(moves):
    if not isinstance(moves, list):
        raise ValueError('잘못된 영역 이동 데이터')

    def point(values, count, low, high):
        return (isinstance(values, list) and len(values) == count
                and all(type(v) in (int, float) and low <= v <= high for v in values))

    for move in moves:
        if not isinstance(move, dict):
            raise ValueError('잘못된 영역 이동 데이터')
        rect = move.get('rect')
        outline = move.get('outline')
        scale = move.get('scale')
        if (not point(rect, 4, 0, 1) or rect[0] >= rect[2] or rect[1] >= rect[3]
                or not point(move.get('offset'), 2, -1, 1)
                or type(scale) is not int or not 10 <= scale <= 200
                or not isinstance(outline, list) or len(outline) > 100000
                or not all(point(vertex, 2, 0, 1) for vertex in outline)):
            raise ValueError('잘못된 영역 이동 범위')
