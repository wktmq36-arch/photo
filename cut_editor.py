import copy
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF,QSize,Signal,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QImage,QPixmap,QKeySequence,QShortcut,QPainterPath
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QListWidget,QListWidgetItem,QSplitter,QDialogButtonBox,QMessageBox,QSpinBox,QLineEdit,
    QAbstractItemView,QMenu,QCheckBox)
from composition import empty_composition,paired_asset,pixel_asset,decode_asset,render_composition
from imaging import read_pixels,render_entry,render_clones,render_regions,crop_base


def pixmap_for(image):
    rgba=image.convert('RGBA')
    return QPixmap.fromImage(QImage(rgba.tobytes(),rgba.width,rgba.height,rgba.width*4,QImage.Format.Format_RGBA8888).copy())


class ImageCanvas(QWidget):
    """Shared image coordinates, corner handles, and cursor-anchored view zoom."""
    def __init__(self):
        super().__init__();self.setMinimumSize(220,220);self.setMouseTracking(True)
        self.pixmap=None;self.target=QRectF();self.view_zoom=1.;self.pan=QPointF();self.pan_start=None
        self.start=None;self.end=None;self.original_rect=None;self.handle=None
    def set_image(self,image,reset=False):
        self.pixmap=pixmap_for(image) if image is not None else None
        if reset:self.reset_view()
        self.update_target();self.update()
    def reset_view(self):
        self.view_zoom=1.;self.pan=QPointF();self.update_target();self.update()
    def update_target(self):
        if not self.pixmap:return
        size=self.pixmap.size();ratio=min(self.width()/size.width(),self.height()/size.height())*self.view_zoom
        w,h=size.width()*ratio,size.height()*ratio
        self.target=QRectF((self.width()-w)/2+self.pan.x(),(self.height()-h)/2+self.pan.y(),w,h)
    def point(self,pos):
        return [max(0.,min(1.,(pos.x()-self.target.x())/max(1,self.target.width()))),
                max(0.,min(1.,(pos.y()-self.target.y())/max(1,self.target.height())))]
    def image_rect(self,rect):
        x1,y1,x2,y2=rect
        return QRectF(self.target.x()+x1*self.target.width(),self.target.y()+y1*self.target.height(),
                      (x2-x1)*self.target.width(),(y2-y1)*self.target.height())
    def handles(self,rect):
        r=self.image_rect(rect);x,y,cx,cy,right,bottom=r.left(),r.top(),r.center().x(),r.center().y(),r.right(),r.bottom()
        return {'nw':QPointF(x,y),'n':QPointF(cx,y),'ne':QPointF(right,y),'e':QPointF(right,cy),
                'se':QPointF(right,bottom),'s':QPointF(cx,bottom),'sw':QPointF(x,bottom),'w':QPointF(x,cy)}
    def handle_at(self,rect,pos):
        return next((key for key,point in self.handles(rect).items() if abs(point.x()-pos.x())<=8 and abs(point.y()-pos.y())<=8),None)
    def draw_handles(self,painter,rect):
        painter.setPen(QPen(QColor('#202630'),1));painter.setBrush(QColor('white'))
        for point in self.handles(rect).values():painter.drawRect(QRectF(point.x()-4,point.y()-4,8,8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    def moved_rect(self,rect,delta):
        dx=max(-rect[0],min(1-rect[2],delta[0]));dy=max(-rect[1],min(1-rect[3],delta[1]))
        return [rect[0]+dx,rect[1]+dy,rect[2]+dx,rect[3]+dy]
    def resized_rect(self,rect,point,handle):
        result=rect[:];minimum_x=min(.01,6/max(1,self.target.width()));minimum_y=min(.01,6/max(1,self.target.height()))
        if 'w' in handle:result[0]=max(0.,min(rect[2]-minimum_x,point[0]))
        if 'e' in handle:result[2]=min(1.,max(rect[0]+minimum_x,point[0]))
        if 'n' in handle:result[1]=max(0.,min(rect[3]-minimum_y,point[1]))
        if 's' in handle:result[3]=min(1.,max(rect[1]+minimum_y,point[1]))
        return result
    def rectangle(self,start,end):
        a=self.point(start);b=self.point(end)
        return [min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])]
    def valid_drag(self,rect):return (rect[2]-rect[0])*self.target.width()>4 and (rect[3]-rect[1])*self.target.height()>4
    def begin_pan(self,event):
        if self.pixmap and (event.button()==Qt.MouseButton.MiddleButton or
            (event.button()==Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier)):
            self.pan_start=event.position();self.setCursor(Qt.CursorShape.ClosedHandCursor);event.accept();return True
        return False
    def continue_pan(self,event):
        if self.pan_start is None:return False
        self.pan+=event.position()-self.pan_start;self.pan_start=event.position();self.update_target();self.update();return True
    def end_pan(self,event):
        if self.pan_start is None:return False
        self.pan_start=None;self.unsetCursor();return True
    def zoom_view(self,event):
        if not self.pixmap:return
        self.update_target();point=event.position()
        u=(point.x()-self.target.x())/self.target.width();v=(point.y()-self.target.y())/self.target.height()
        self.view_zoom=max(.25,min(16.,self.view_zoom*1.2**(event.angleDelta().y()/120)));self.update_target()
        self.pan+=QPointF(point.x()-(self.target.x()+u*self.target.width()),point.y()-(self.target.y()+v*self.target.height()))
        self.update_target();self.update();event.accept()
    def paint_image(self,painter):
        painter.fillRect(self.rect(),QColor('#171b22'));self.update_target()
        if self.pixmap:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(self.target,self.pixmap,QRectF(self.pixmap.rect()))


class SourceCanvas(ImageCanvas):
    selectionChanged=Signal(object)
    def __init__(self):
        super().__init__();self.selection=None;self.action=None
    def clear_selection(self):
        self.selection=None;self.selectionChanged.emit(None);self.update()
    def paintEvent(self,event):
        painter=QPainter(self);self.paint_image(painter)
        if not self.pixmap:return
        rect=self.selection
        if self.action=='draw' and self.start is not None:rect=self.rectangle(self.start,self.end)
        if rect:
            selected=self.image_rect(rect);t=self.target
            painter.save();painter.setClipRect(t);shade=QColor(0,0,0,125)
            for area in [QRectF(t.left(),t.top(),t.width(),selected.top()-t.top()),QRectF(t.left(),selected.bottom(),t.width(),t.bottom()-selected.bottom()),
                         QRectF(t.left(),selected.top(),selected.left()-t.left(),selected.height()),QRectF(selected.right(),selected.top(),t.right()-selected.right(),selected.height())]:
                painter.fillRect(area,shade)
            painter.restore();painter.setBrush(Qt.BrushStyle.NoBrush);painter.setPen(QPen(QColor('#ffb347'),2));painter.drawRect(selected)
            self.draw_handles(painter,rect)
    def mousePressEvent(self,event):
        if self.begin_pan(event):return
        if event.button()!=Qt.MouseButton.LeftButton or not self.pixmap:return
        self.update_target();self.handle=self.handle_at(self.selection,event.position()) if self.selection else None
        if not self.handle and not self.target.contains(event.position()):return
        self.start=event.position();self.end=self.start;self.original_rect=self.selection[:] if self.selection else None
        if self.handle:self.action='resize'
        elif self.selection and self.image_rect(self.selection).contains(event.position()) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:self.action='move'
        else:self.action='draw'
        self.update()
    def mouseMoveEvent(self,event):
        if self.continue_pan(event):return
        if self.start is None:return
        self.end=event.position()
        if self.action=='resize':self.selection=self.resized_rect(self.original_rect,self.point(self.end),self.handle)
        elif self.action=='move':
            a,b=self.point(self.start),self.point(self.end);self.selection=self.moved_rect(self.original_rect,[b[0]-a[0],b[1]-a[1]])
        self.update()
    def mouseReleaseEvent(self,event):
        if self.end_pan(event):return
        if self.start is None:return
        if self.action=='draw':
            rect=self.rectangle(self.start,event.position())
            self.selection=rect if self.valid_drag(rect) else None
        self.start=None;self.end=None;self.action=None;self.selectionChanged.emit(self.selection);self.update()
    def wheelEvent(self,event):self.zoom_view(event)


class PanelCanvas(ImageCanvas):
    picked=Signal(object);dragged=Signal(object);zoomed=Signal(object);copied=Signal(object);finished=Signal()
    created=Signal(object);geometryChanged=Signal(object)
    nudged=Signal(object);lineDrawn=Signal(object)
    def __init__(self):
        super().__init__();self.cells=[];self.active=0;self.mode='frame';self.action=None;self.show_guides=True
        self.ink_points=[];self.ink_width=.005;self.ink_constrained=False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    def paintEvent(self,event):
        painter=QPainter(self);self.paint_image(painter)
        if not self.pixmap or not self.show_guides:return
        if self.ink_points:
            painter.save();painter.setClipRect(self.target);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor('black'),max(1,self.ink_width*self.target.width()),Qt.PenStyle.SolidLine,Qt.PenCapStyle.FlatCap if self.ink_constrained or self.action=='line' else Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            path=QPainterPath()
            for index,(x,y) in enumerate(self.ink_points):
                point=QPointF(self.target.x()+x*self.target.width(),self.target.y()+y*self.target.height())
                if index==0:path.moveTo(point)
                else:path.lineTo(point)
            if len(self.ink_points)==1:painter.drawPoint(path.currentPosition())
            else:painter.drawPath(path)
            painter.restore()
        if self.mode in ('ink','line'):return
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index,cell in enumerate(self.cells):
            rect=self.image_rect(cell['rect']);painter.setPen(QPen(QColor('#ffb347' if index==self.active else '#65baff'),2 if index==self.active else 1))
            painter.drawRect(rect.adjusted(-3,-3,3,3));painter.drawText(rect.adjusted(7,6,-4,-4),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft,str(index+1))
        if self.mode in ('draw','copy') and self.start is not None and self.end is not None:
            painter.setPen(QPen(QColor('white'),2,Qt.PenStyle.DashLine));painter.drawRect(self.image_rect(self.rectangle(self.start,self.end)))
        elif 0<=self.active<len(self.cells):self.draw_handles(painter,self.cells[self.active]['rect'])
    def mousePressEvent(self,event):
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if self.begin_pan(event):return
        if not self.show_guides:return
        if event.button()!=Qt.MouseButton.LeftButton or not self.pixmap:return
        self.update_target();pos=event.position();self.handle=None
        if self.mode not in ('draw','copy','vertical','horizontal','ink','line') and 0<=self.active<len(self.cells):self.handle=self.handle_at(self.cells[self.active]['rect'],pos)
        if not self.handle and not self.target.contains(pos):return
        self.start=pos;self.end=pos
        if self.mode in ('ink','line'):
            self.action=self.mode;self.ink_constrained=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier);self.ink_points=[self.point(pos)];self.update();return
        if self.mode in ('draw','copy'):self.action=self.mode;self.update();return
        point=self.point(pos)
        index=self.active if self.handle else next((i for i in reversed(range(len(self.cells))) if self.image_rect(self.cells[i]['rect']).contains(pos)),-1)
        if index<0:self.start=None;return
        self.active=index;self.original_rect=self.cells[index]['rect'][:]
        self.action='resize' if self.handle else ('frame' if self.mode=='frame' else 'image')
        self.picked.emit((index,point,self.mode));self.update()
    def update_ink(self,pos,modifiers):
        self.ink_constrained=bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        point=self.point(pos)
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            start=self.ink_points[0];width,height=getattr(self,'ink_image_size',(self.pixmap.width(),self.pixmap.height()))
            width,height=max(1,width-1),max(1,height-1)
            dx,dy=(point[0]-start[0])*width,(point[1]-start[1])*height
            if abs(dy)<=abs(dx)*.41421356237:dy=0.
            elif abs(dx)<=abs(dy)*.41421356237:dx=0.
            else:
                distance=(abs(dx)+abs(dy))/2;dx=distance if dx>=0 else -distance;dy=distance if dy>=0 else -distance
            dx,dy=dx/width,dy/height;scale=1.
            for coordinate,delta in zip(start,(dx,dy)):
                if delta>0:scale=min(scale,(1-coordinate)/delta)
                elif delta<0:scale=min(scale,-coordinate/delta)
            point=[max(0.,min(1.,start[0]+dx*scale)),max(0.,min(1.,start[1]+dy*scale))]
            self.ink_points=[start,point]
        elif self.action=='line':self.ink_points=self.ink_points[:1]+[point]
        elif point!=self.ink_points[-1]:self.ink_points.append(point)
    def mouseMoveEvent(self,event):
        if self.continue_pan(event):return
        if self.start is None:return
        pos=event.position()
        if self.action in ('ink','line'):
            self.update_ink(pos,event.modifiers())
        elif self.action=='resize':self.geometryChanged.emit((self.active,self.resized_rect(self.original_rect,self.point(pos),self.handle)))
        elif self.action=='frame':
            a,b=self.point(self.start),self.point(pos)
            self.geometryChanged.emit((self.active,self.moved_rect(self.original_rect,[b[0]-a[0],b[1]-a[1]])))
        elif self.action=='image':
            a,b=self.point(self.end),self.point(pos);self.dragged.emit([b[0]-a[0],b[1]-a[1]])
        self.end=pos;self.update()
    def mouseReleaseEvent(self,event):
        if self.end_pan(event):return
        if self.start is None:return
        if self.action in ('ink','line'):
            modifiers=event.modifiers()
            if self.ink_constrained:modifiers|=Qt.KeyboardModifier.ShiftModifier
            self.update_ink(event.position(),modifiers)
            self.lineDrawn.emit({'points':copy.deepcopy(self.ink_points),'width':self.ink_width,'cap':'flat' if self.ink_constrained or self.action=='line' else 'round'});self.ink_points=[];self.ink_constrained=False
        if self.action in ('draw','copy'):
            rect=self.rectangle(self.start,event.position())
            if self.valid_drag(rect):
                if self.action=='draw':self.created.emit(rect)
                else:self.copied.emit(rect)
        self.start=None;self.end=None;self.action=None;self.finished.emit();self.update()
    def wheelEvent(self,event):
        if self.mode in ('ink','line') or event.modifiers() & Qt.KeyboardModifier.ControlModifier:self.zoom_view(event)
        elif self.target.contains(event.position()) and 0<=self.active<len(self.cells):self.zoomed.emit(event.angleDelta().y()/120);event.accept()
        else:event.ignore()
    def keyPressEvent(self,event):
        directions={Qt.Key.Key_Left:(-1,0),Qt.Key.Key_Right:(1,0),Qt.Key.Key_Up:(0,-1),Qt.Key.Key_Down:(0,1)}
        if event.key() in directions and not event.modifiers() & (Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.AltModifier):
            dx,dy=directions[event.key()];step=10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            self.nudged.emit((dx*step,dy*step));event.accept();return
        super().keyPressEvent(event)


class CutEditor(QDialog):
    historyChanged=Signal()
    def __init__(self,entry,entries,icons,clipboard=None,parent=None,embedded=False):
        super().__init__(parent);self.setWindowTitle('컷 편집 · 왼쪽에서 선택하고 오른쪽에 붙여넣기')
        self.embedded=embedded
        if embedded:self.setWindowFlags(Qt.WindowType.Widget)
        available=self.screen().availableGeometry();self.resize(min(1420,available.width()-40),min(900,available.height()-60))
        self.entry=entry;self.entries=entries;self.clipboard=clipboard;self.source_image=None;self.source_uncensored=None;self.source_dirty=False
        self.composition=copy.deepcopy(entry.get('composition') or empty_composition())
        self.history=[];self.redo_history=[];self.gesture=None;self.assets_cache={}
        self.raw=read_pixels(entry['path']);self.base=crop_base(self.raw,entry);self.preview=self.base.copy();self.preview.thumbnail((1600,1600))
        root=QVBoxLayout(self);intro=QLabel('원본 영역 선택 → 컷 그리기 → 붙여넣기')
        intro.setStyleSheet('font-size:14px;font-weight:bold;padding:4px;')
        header=QHBoxLayout();root.addLayout(header);header.addWidget(intro,1)
        self.source_toggle=QPushButton('원본 접기');header.addWidget(self.source_toggle)
        self.final_preview=QCheckBox('완성본 보기');header.addWidget(self.final_preview)
        split=QSplitter();split.setHandleWidth(5);root.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,3,0)
        self.search=QLineEdit();self.search.setPlaceholderText('가져올 그림 찾기 · 번호 또는 파일명');self.search.textChanged.connect(self.filter_sources);ll.addWidget(self.search)
        self.sources=QListWidget();self.sources.setViewMode(QListWidget.ViewMode.IconMode);self.sources.setMovement(QListWidget.Movement.Static)
        self.sources.setIconSize(QSize(72,55));self.sources.setGridSize(QSize(110,86));self.sources.setFlow(QListWidget.Flow.LeftToRight);self.sources.setWrapping(False)
        self.sources.setFixedHeight(110);ll.addWidget(self.sources)
        for index,source in enumerate(entries):self.sources.addItem(QListWidgetItem(icons[index],f'{index+1:03d}  {Path(source["path"]).name}'))
        self.source_title=QLabel('');self.source_title.setWordWrap(True);ll.addWidget(self.source_title)
        self.source_canvas=SourceCanvas();ll.addWidget(self.source_canvas,1)
        source_controls=QHBoxLayout();ll.addLayout(source_controls)
        for label,fn in [('전체 선택',self.select_whole_source),('화면 맞춤',self.source_canvas.reset_view)]:
            button=QPushButton(label);button.clicked.connect(fn);source_controls.addWidget(button)
        self.source_info=QLabel('드래그: 영역 선택 · 모서리: 범위 조절 · 휠: 확대');self.source_info.setWordWrap(True);ll.addWidget(self.source_info)
        split.addWidget(left)
        self.source_toggle.clicked.connect(lambda:self.toggle_source(left))
        right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(3,0,0,0)
        title=QLabel(f'대상: {Path(entry["path"]).name}  ·  출력 {self.base.width} × {self.base.height}px');title.setWordWrap(True);rl.addWidget(title)
        toolbar=QHBoxLayout();rl.addLayout(toolbar);self.mode_buttons={}
        for mode,label in [('draw','＋ 컷 그리기'),('frame','컷 이동'),('move','그림 위치')]:
            button=QPushButton(label);button.setCheckable(True);button.clicked.connect(lambda checked,m=mode:self.set_mode(m));toolbar.addWidget(button);self.mode_buttons[mode]=button
        more_button=QPushButton('더 보기');menu=QMenu(more_button)
        for label,fn in [('세로 분할선',lambda:self.set_mode('vertical')),('가로 분할선',lambda:self.set_mode('horizontal')),
                         ('붙인 그림 비우기',self.remove_layer),('선택 컷 삭제',self.delete_cell),('선택 컷 앞으로',self.raise_cell),('컷 배치 초기화',self.reset),('화면 맞춤',lambda:self.canvas.reset_view())]:
            menu.addAction(label,fn)
        more_button.setMenu(menu);toolbar.addWidget(more_button)
        self.canvas=PanelCanvas();self.canvas.ink_image_size=self.base.size;rl.addWidget(self.canvas,1)
        self.canvas.picked.connect(self.pick);self.canvas.dragged.connect(self.move_layer);self.canvas.zoomed.connect(self.scale_layer)
        self.canvas.finished.connect(self.finish_gesture);self.canvas.copied.connect(self.copy_region)
        self.canvas.created.connect(self.add_cell);self.canvas.geometryChanged.connect(self.change_geometry)
        self.canvas.nudged.connect(self.nudge);self.canvas.lineDrawn.connect(self.add_line)
        line_tools=QHBoxLayout();rl.addLayout(line_tools)
        for mode,label in [('ink','자유선'),('line','직선')]:
            button=QPushButton(label);button.setCheckable(True);button.clicked.connect(lambda checked,m=mode:self.set_mode(m));line_tools.addWidget(button);self.mode_buttons[mode]=button
        line_tools.addWidget(QLabel('선 굵기 px'))
        self.line_width=QSpinBox();self.line_width.setRange(1,max(1,min(200,round(self.base.width*.2))));self.line_width.setValue(min(4,self.line_width.maximum()));self.line_width.setFixedWidth(64)
        self.line_width.setToolTip('새로 그릴 선의 굵기 · 크기 변경은 실행 취소에 포함되지 않습니다.')
        self.line_width.valueChanged.connect(lambda value:setattr(self.canvas,'ink_width',value/self.base.width));self.canvas.ink_width=self.line_width.value()/self.base.width;line_tools.addWidget(self.line_width)
        remove_line=QPushButton('마지막 선 삭제');remove_line.clicked.connect(self.remove_last_line);line_tools.addWidget(remove_line);line_tools.addStretch()
        self.final_preview.toggled.connect(self.show_final_preview)
        actions=QHBoxLayout();rl.addLayout(actions)
        self.paste_button=QPushButton('선택 부분 붙여넣기 →');self.paste_button.clicked.connect(self.paste)
        self.paste_button.setStyleSheet('background:#287fce;color:white;font-weight:bold;padding:9px;');actions.addWidget(self.paste_button)
        fill=QPushButton('선택 부분 전체로 늘리기');fill.setToolTip('선택한 부분 전체를 대상 가로×세로 크기로 늘립니다. 비율이 달라도 추가로 자르지 않습니다.');fill.clicked.connect(self.fill_original_resolution);actions.addWidget(fill)
        fit_controls=QHBoxLayout();rl.addLayout(fit_controls)
        for label,fn in [('그림 전체 보이게',lambda:self.fit(False)),('컷에 꽉 채우기',lambda:self.fit(True)),('-',lambda:self.scale_layer(-1)),('+',lambda:self.scale_layer(1))]:
            button=QPushButton(label);button.clicked.connect(fn);fit_controls.addWidget(button)
        self.scale_label=QLabel('');fit_controls.addWidget(self.scale_label)
        self.help=QLabel('드래그로 새 컷 · 모서리로 크기 조절 · 그림 위치에서 드래그/휠로 내용 조절');self.help.setWordWrap(True);rl.addWidget(self.help)
        split.addWidget(right);split.setSizes([560,820]);split.setChildrenCollapsible(False)
        bottom=QHBoxLayout();root.addLayout(bottom)
        for label,fn in [('실행 취소',self.undo),('다시 실행',self.redo)]:
            button=QPushButton(label);button.clicked.connect(fn);bottom.addWidget(button)
        bottom.addWidget(QLabel('흰 간격 / 테두리 px'))
        self.gutter=QSpinBox();self.gutter.setRange(0,min(200,self.base.width//10));self.gutter.valueChanged.connect(self.change_gutter);bottom.addWidget(self.gutter)
        bottom.addWidget(QLabel('선택 컷 검은선 px'))
        self.border=QSpinBox();self.border.setRange(0,min(200,self.base.width//10));self.border.setToolTip('0은 테두리 없음. 선택한 컷에 적용되고 출력에도 포함됩니다.')
        self.border.valueChanged.connect(self.change_border);bottom.addWidget(self.border)
        self.info=QLabel();bottom.addWidget(self.info,1)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('모자이크 모드로' if embedded else '적용');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('편집 취소' if embedded else '취소')
        buttons.accepted.connect(self.apply);buttons.rejected.connect(self.reject);bottom.addWidget(buttons)
        self.shortcuts=[]
        for sequence,fn in [('Ctrl+C',self.copy_selection),('Ctrl+V',self.paste),('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),('Ctrl+Shift+Z',self.redo)]:
            if embedded and sequence in ('Ctrl+Z','Ctrl+Y','Ctrl+Shift+Z'):continue
            shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(fn);self.shortcuts.append(shortcut)
        for button in self.findChildren(QPushButton):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if embedded:button.setAutoDefault(False);button.setDefault(False)
        self.border.lineEdit().returnPressed.connect(self.canvas.setFocus)
        self.gutter.lineEdit().returnPressed.connect(self.canvas.setFocus)
        self.line_width.lineEdit().returnPressed.connect(self.canvas.setFocus)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(16);self.timer.timeout.connect(self.refresh)
        self.sources.currentRowChanged.connect(self.load_source);self.source_canvas.selectionChanged.connect(self.source_selected)
        if clipboard:
            self.source_image=decode_asset(clipboard[1]);self.source_uncensored=decode_asset(clipboard[2] if len(clipboard)>2 else clipboard[1]);self.source_canvas.set_image(self.preview_source(),True);self.source_title.setText('복사해 둔 그림 · 드래그해서 필요한 부분 선택')
        elif entries:self.sources.setCurrentRow(next((i for i,e in enumerate(entries) if e['id']==entry['id']),0))
        self.set_mode('frame' if entry.get('composition') else 'draw');self.refresh()
    def toggle_source(self,widget):
        widget.setVisible(not widget.isVisible());self.source_toggle.setText('원본 접기' if widget.isVisible() else '원본 펼치기')
    def keyPressEvent(self,event):
        if self.embedded and event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
            self.canvas.setFocus();event.accept();return
        super().keyPressEvent(event)
    def show_final_preview(self,enabled):
        self.canvas.show_guides=not enabled;self.canvas.update();self.canvas.setFocus()
    def nudge(self,delta):
        cell=self.cell()
        if cell is None:return
        dx,dy=delta
        if self.canvas.mode=='move' and 'asset' in cell:
            x1,y1,x2,y2=cell['rect'];offset=cell.get('offset',[0.,0.])
            new=[max(-100.,min(100.,offset[0]+dx/self.base.width/(x2-x1))),max(-100.,min(100.,offset[1]+dy/self.base.height/(y2-y1)))]
            if new==offset:return
            self.record();cell['offset']=new
        else:
            rect=self.canvas.moved_rect(cell['rect'],[dx/self.base.width,dy/self.base.height])
            if rect==cell['rect']:return
            self.record()
            self.change_geometry((self.canvas.active,rect))
        self.refresh()
    def filter_sources(self,text):
        for row in range(self.sources.count()):self.sources.item(row).setHidden(text.casefold() not in self.sources.item(row).text().casefold())
    def preview_source(self):
        image=self.source_image.copy();image.thumbnail((1800,1800));return image
    def load_source(self,row):
        if row<0:return
        try:
            source=self.entries[row]
            if source['id']==self.entry['id']:source=dict(source,composition=self.composition)
            raw=read_pixels(source['path']);self.source_image=render_entry(raw,source)
            self.source_uncensored=render_entry(raw,source,include_mosaic=False)
            self.source_canvas.selection=None;self.source_canvas.set_image(self.preview_source(),True)
            self.source_title.setText(Path(source['path']).name);self.source_selected(None)
        except Exception as exc:
            self.source_image=None;self.source_canvas.set_image(None);self.source_title.setText(f'읽기 실패: {exc}')
            self.clipboard=None;self.source_dirty=False
    def source_selected(self,rect):
        self.source_dirty=True
        if self.source_image is None:return
        box=self.source_box();width,height=box[2]-box[0],box[3]-box[1]
        self.source_info.setText(f'선택 {width} × {height}px · 모서리: 범위 조절 · 안쪽: 이동 · Shift+드래그: 새 선택 · 휠: 화면 확대')
    def source_box(self):
        w,h=self.source_image.size;rect=self.source_canvas.selection or [0.,0.,1.,1.]
        x1,y1,x2,y2=rect
        left,top=min(w-1,round(x1*w)),min(h-1,round(y1*h))
        return (left,top,max(left+1,min(w,round(x2*w))),max(top+1,min(h,round(y2*h))))
    def select_whole_source(self):self.source_canvas.clear_selection()
    def copy_selection(self):
        if self.source_image is None:return
        if self.source_dirty or self.clipboard is None:
            self.clipboard=paired_asset(self.source_image.crop(self.source_box()),(self.source_uncensored if self.source_uncensored is not None else self.source_image).crop(self.source_box()));self.source_dirty=False
        self.info.setText('선택 부분 복사 완료 · 대상에 붙여넣으세요.')
    def copy_source(self):
        self.select_whole_source();self.copy_selection()
    def set_mode(self,mode):
        self.canvas.mode=mode
        self.canvas.setFocus()
        for key,button in self.mode_buttons.items():button.setChecked(key==mode)
        messages={'ink':'마우스로 자유선 · Shift+드래그: 수평/수직/45도 직선 · 휠: 화면 확대 · Ctrl+드래그: 이동',
                  'line':'드래그: 직선 · Shift: 수평/수직/45도 고정 · 휠: 화면 확대',
                  'draw':'대상 그림에서 드래그하여 원하는 크기의 새 컷을 만드세요.',
                  'frame':'드래그/방향키: 컷 이동 · Shift+방향키: 10px · 모서리: 크기 조절',
                  'move':'드래그/방향키: 그림 위치 · Shift+방향키: 10px · 휠: 그림 확대/축소',
                  'vertical':'나눌 컷의 원하는 위치를 클릭하면 세로로 나뉩니다.',
                  'horizontal':'나눌 컷의 원하는 위치를 클릭하면 가로로 나뉩니다.'}
        self.help.setText(messages.get(mode,''))
    def record(self):
        self.finish_gesture();self.history.append(copy.deepcopy(self.composition));self.history=self.history[-1000:];self.redo_history.clear()
    def update_image(self):
        if not self.timer.isActive():self.timer.start()
    def refresh(self):
        self.timer.stop();image=render_composition(self.preview,self.composition,self.assets_cache)
        image=render_clones(image,self.entry.get('clones',[]));image=render_regions(image,self.entry['regions'])
        self.canvas.set_image(image);self.canvas.cells=self.composition['cells']
        self.canvas.active=min(self.canvas.active,len(self.canvas.cells)-1)
        self.gutter.blockSignals(True);self.gutter.setValue(round(self.composition.get('gutter',0.)*self.base.width));self.gutter.blockSignals(False)
        self.info.setText(f'컷 {len(self.canvas.cells)}개 · 선택 {self.canvas.active+1}번' if self.canvas.active>=0 else '컷을 그리거나 원래 해상도로 채우세요.')
        cell=self.cell();self.scale_label.setText(f'{cell.get("scale",1.)*100:.0f}%' if cell and 'asset' in cell else '')
        self.border.blockSignals(True);self.border.setEnabled(cell is not None);self.border.setValue(round(cell.get('border',0.)*self.base.width) if cell else 0);self.border.blockSignals(False)
        self.historyChanged.emit()
    def pick(self,event):
        index,point,mode=event;self.finish_gesture();self.canvas.active=index
        if mode in ('vertical','horizontal'):
            cell=self.cell();rect=cell['rect'];axis=0 if mode=='vertical' else 1;value=point[axis]
            if not rect[axis]+.01<value<rect[axis+2]-.01:return
            self.record();first=copy.deepcopy(cell);second=copy.deepcopy(cell)
            first['rect'][axis+2]=value;second['rect'][axis]=value
            self.composition['cells'][index:index+1]=[first,second];self.set_mode('frame');self.refresh()
        elif mode in ('move','frame'):
            self.gesture=copy.deepcopy(self.composition);self.update_image()
    def add_line(self,line):
        self.record();self.composition.setdefault('lines',[]).append(copy.deepcopy(line));self.refresh()
    def remove_last_line(self):
        if not self.composition.get('lines'):return
        self.record();self.composition['lines'].pop();self.refresh();self.canvas.setFocus()
    def add_cell(self,rect):
        self.record()
        # Replace the legacy empty full-image placeholder on the first free cut.
        if self.composition['cells']==[{'rect':[0.,0.,1.,1.]}]:self.composition['cells']=[]
        self.composition['freeform']=True;self.composition['cells'].append({'rect':rect[:]})
        self.canvas.active=len(self.composition['cells'])-1;self.set_mode('frame');self.refresh()
    def change_geometry(self,event):
        index,rect=event
        if 0<=index<len(self.composition['cells']):
            self.composition['cells'][index]['rect']=rect;self.composition['freeform']=True;self.update_image()
    def change_gutter(self,value):
        if value==round(self.composition.get('gutter',0.)*self.base.width):return
        self.record();self.composition['gutter']=value/self.base.width;self.refresh()
    def change_border(self,value):
        cell=self.cell()
        if cell is None or value==round(cell.get('border',0.)*self.base.width):return
        self.record();cell['border']=value/self.base.width;self.refresh()
    def finish_gesture(self):
        if self.gesture is not None and self.gesture!=self.composition:
            self.history.append(self.gesture);self.history=self.history[-1000:];self.redo_history.clear()
        self.gesture=None
    def cell(self):
        return self.composition['cells'][self.canvas.active] if 0<=self.canvas.active<len(self.composition['cells']) else None
    def copy_region(self,rect):
        image=render_entry(self.raw,dict(self.entry,composition=self.composition))
        box=(round(rect[0]*image.width),round(rect[1]*image.height),round(rect[2]*image.width),round(rect[3]*image.height))
        if box[2]>box[0] and box[3]>box[1]:
            uncensored=render_entry(self.raw,dict(self.entry,composition=self.composition),include_mosaic=False)
            self.clipboard=paired_asset(image.crop(box),uncensored.crop(box));self.source_image=decode_asset(self.clipboard[1]);self.source_uncensored=decode_asset(self.clipboard[2]);self.source_canvas.selection=None
            self.source_canvas.set_image(self.preview_source(),True);self.source_dirty=False
        self.set_mode('move');self.refresh();self.canvas.setFocus()
    def store_clipboard(self):
        key,data=self.clipboard[:2];self.composition['assets'][key]=data
        if len(self.clipboard)>2:self.composition.setdefault('uncensored_assets',{})[key]=self.clipboard[2]
        return key
    def paste(self):
        self.copy_selection()
        if not self.clipboard:self.info.setText('먼저 왼쪽에서 가져올 그림을 선택하세요.');return
        self.record()
        if self.cell() is None:
            self.composition['cells'].append({'rect':[.1,.1,.9,.9]});self.canvas.active=len(self.composition['cells'])-1;self.composition['freeform']=True
        key=self.store_clipboard();self.cell().update(asset=key,scale=1.,offset=[0.,0.])
        self.set_mode('move');self.refresh();self.canvas.setFocus()
    def fill_original_resolution(self):
        self.copy_selection()
        if not self.clipboard:self.info.setText('먼저 왼쪽에서 필요한 부분을 선택하세요.');return
        self.record();key=self.store_clipboard()
        # Keep earlier cuts editable underneath; this full-canvas cut is on top.
        if self.composition['cells']==[{'rect':[0.,0.,1.,1.]}]:self.composition['cells']=[]
        self.composition['cells'].append({'rect':[0.,0.,1.,1.],'asset':key,'scale':1.,'offset':[0.,0.],'stretch':True})
        self.composition['freeform']=True;self.canvas.active=len(self.composition['cells'])-1;self.set_mode('move');self.refresh()
        self.info.setText(f'선택 부분을 {self.base.width} × {self.base.height}px에 채웠습니다. 휠/드래그로 구도 조절')
    def move_layer(self,delta):
        cell=self.cell()
        if not cell or 'asset' not in cell:return
        x1,y1,x2,y2=cell['rect'];ox,oy=cell.get('offset',[0.,0.])
        cell['offset']=[max(-100.,min(100.,ox+delta[0]/(x2-x1))),max(-100.,min(100.,oy+delta[1]/(y2-y1)))];self.update_image()
    def scale_layer(self,steps):
        cell=self.cell()
        if not cell or 'asset' not in cell or not steps:return
        value=max(.05,min(32.,cell.get('scale',1.)*1.15**steps))
        if value==cell.get('scale',1.):return
        self.record();cell['scale']=value;self.refresh()
    def fit(self,cover):
        cell=self.cell()
        if not cell or 'asset' not in cell:return
        self.record();cell.pop('stretch',None);source=self.assets_cache[cell['asset']];x1,y1,x2,y2=cell['rect'];w,h=(x2-x1)*self.base.width,(y2-y1)*self.base.height
        cell['scale']=1. if cover else max(.05,min(32.,min(w/source.width,h/source.height)/max(w/source.width,h/source.height)))
        cell['offset']=[0.,0.];self.refresh()
    def remove_layer(self):
        cell=self.cell()
        if not cell or 'asset' not in cell:return
        self.record();self.composition['cells'][self.canvas.active]={k:v for k,v in cell.items() if k not in ('asset','scale','offset')};self.refresh()
    def delete_cell(self):
        if self.cell() is None:return
        self.record();self.composition['cells'].pop(self.canvas.active);self.refresh()
    def raise_cell(self):
        if self.cell() is None or self.canvas.active==len(self.composition['cells'])-1:return
        self.record();cell=self.composition['cells'].pop(self.canvas.active);self.composition['cells'].append(cell)
        self.canvas.active=len(self.composition['cells'])-1;self.refresh()
    def reset(self):
        self.record();self.composition=empty_composition();self.canvas.active=0;self.set_mode('draw');self.refresh()
    def undo(self):
        self.finish_gesture()
        if not self.history:return
        self.redo_history.append(copy.deepcopy(self.composition));self.composition=self.history.pop();self.refresh()
    def redo(self):
        if not self.redo_history:return
        self.history.append(copy.deepcopy(self.composition));self.composition=self.redo_history.pop();self.refresh()
    def apply(self):
        self.finish_gesture();used={c['asset'] for c in self.composition['cells'] if 'asset' in c}
        self.composition['assets']={k:v for k,v in self.composition['assets'].items() if k in used}
        if 'uncensored_assets' in self.composition:self.composition['uncensored_assets']={k:v for k,v in self.composition['uncensored_assets'].items() if k in used}
        self.accept()
