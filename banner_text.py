"""Banner typography in output pixel coordinates; {count} is resolved at export."""
from pathlib import Path
import math
import os
from PIL import ImageDraw,ImageFont


DEFAULT_TEXT={'enabled':True,'ja':'全 {count}枚','en':'{count} images','size':.08,'position':'bottom-right','font':'yu'}
FONTS={'yu':('YuGothB.ttc','Yu Gothic Bold'),'meiryo':('meiryob.ttc','Meiryo Bold')}
POSITIONS={'bottom-right':'오른쪽 아래','bottom-left':'왼쪽 아래','bottom-center':'가운데 아래',
           'top-right':'오른쪽 위','top-left':'왼쪽 위','center':'정중앙'}


def validate_banner_text(options):
    if not isinstance(options,dict) or not isinstance(options.get('enabled',True),bool):raise ValueError('잘못된 배너 문구 설정')
    for field in ('ja','en'):
        value=options.get(field,DEFAULT_TEXT[field])
        if not isinstance(value,str) or len(value)>200 or any(ord(c)<32 for c in value):raise ValueError('배너 문구는 줄당 200자 이내로 입력하세요.')
    size=options.get('size',.08)
    if not isinstance(size,(int,float)) or not math.isfinite(size) or not .02<=size<=.25:raise ValueError('잘못된 배너 글자 크기')
    if options.get('font','yu') not in FONTS or options.get('position','bottom-right') not in POSITIONS:raise ValueError('잘못된 배너 글꼴/위치')


def font_for(name,size):
    root=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for filename in (FONTS[name][0],'YuGothB.ttc','meiryob.ttc','malgunbd.ttf'):
        path=root/filename
        if path.is_file():return ImageFont.truetype(str(path),size=max(1,size))
    raise RuntimeError('배너용 글꼴이 없습니다. Windows의 Yu Gothic 또는 Meiryo 글꼴을 설치하세요.')


def render_banner_text(image,options,count):
    if not options or not options.get('enabled',True):return image
    validate_banner_text(options)
    lines=[(options.get(field,DEFAULT_TEXT[field]).replace('{count}',str(count)),ratio) for field,ratio in [('ja',1.),('en',.56)]]
    lines=[(text,ratio) for text,ratio in lines if text]
    if not lines:return image
    result=image.convert('RGBA').copy();draw=ImageDraw.Draw(result);w,h=result.size
    margin=max(2,round(min(w,h)*.045));available_w=max(1,w-2*margin);available_h=max(1,h-2*margin)
    size=max(1,round(w*options.get('size',.08)));name=options.get('font','yu')
    def layout(size):
        stroke=max(1,round(size*.045));gap=max(2,round(size*.18));items=[]
        for text,ratio in lines:
            font=font_for(name,max(1,round(size*ratio)));box=draw.textbbox((0,0),text,font=font,stroke_width=stroke,anchor='lt')
            items.append((text,font,box,box[2]-box[0],box[3]-box[1]))
        return items,stroke,gap,max(item[3] for item in items),sum(item[4] for item in items)+gap*(len(items)-1)
    items,stroke,gap,bw,bh=layout(size)
    for _ in range(4):
        if bw<=available_w and bh<=available_h:break
        size=max(1,int(size*min(available_w/max(1,bw),available_h/max(1,bh))*.95));items,stroke,gap,bw,bh=layout(size)
    position=options.get('position','bottom-right');right=position.endswith('right');left=position.endswith('left')
    x=w-margin-bw if right else margin if left else (w-bw)/2
    y=margin if position.startswith('top') else (h-bh)/2 if position=='center' else h-margin-bh
    for text,font,box,tw,th in items:
        tx=x+bw-tw if right else x if left else x+(bw-tw)/2
        origin=(round(tx-box[0]),round(y-box[1]));shadow=max(1,round(size*.035))
        draw.text((origin[0]+shadow,origin[1]+shadow),text,font=font,anchor='lt',fill=(0,0,0,210),stroke_width=stroke+1,stroke_fill=(0,0,0,210))
        draw.text(origin,text,font=font,anchor='lt',fill='white',stroke_width=stroke,stroke_fill='#182333')
        y+=th+gap
    return result
