import copy
from pathlib import Path
from PySide6.QtCore import Qt,QRectF,QPointF,QSize,Signal,QTimer
from PySide6.QtGui import QPainter,QColor,QPen,QImage,QPixmap,QKeySequence,QShortcut
from PySide6.QtWidgets import (QDialog,QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QListWidget,QListWidgetItem,QSplitter,QDialogButtonBox,QMessageBox,QSpinBox)
from composition import empty_composition,pixel_asset,render_composition
from imaging import read_pixels,render_entry,render_clones,render_regions


class PanelCanvas(QWidget):
    picked=Signal(object)
    dragged=Signal(object)
    zoomed=Signal(object)
    copied=Signal(object)
    finished=Signal()
    def __init__(self):
        super().__init__();self.setMinimumSize(360,300);self.pixmap=None;self.cells=[];self.active=0
        self.target=QRectF();self.mode='move';self.start=None;self.end=None;self.setMouseTracking(True)
    def point(self,pos):
        return [max(0.,min(1.,(pos.x()-self.target.x())/max(1,self.target.width()))),max(0.,min(1.,(pos.y()-self.target.y())/max(1,self.target.height())))]
    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#171b22'))
        if not self.pixmap:return
        size=self.pixmap.size();ratio=min(self.width()/size.width(),self.height()/size.height())
        w,h=size.width()*ratio,size.height()*ratio;self.target=QRectF((self.width()-w)/2,(self.height()-h)/2,w,h)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.target,self.pixmap,QRectF(self.pixmap.rect()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for index,cell in enumerate(self.cells):
            x1,y1,x2,y2=cell['rect'];rect=QRectF(self.target.x()+x1*w,self.target.y()+y1*h,(x2-x1)*w,(y2-y1)*h)
            painter.setPen(QPen(QColor('#ffb347' if index==self.active else '#65baff'),3 if index==self.active else 1))
            painter.drawRect(rect);painter.drawText(rect.adjusted(6,5,-4,-4),Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft,str(index+1))
        if self.mode=='copy' and self.start is not None and self.end is not None:
            painter.setPen(QPen(QColor('white'),2,Qt.PenStyle.DashLine));painter.drawRect(QRectF(self.start,self.end).normalized())
    def mousePressEvent(self,event):
        if event.button()!=Qt.MouseButton.LeftButton or not self.target.contains(event.position()):return
        self.start=event.position();self.end=self.start;point=self.point(self.start)
        index=next((i for i,c in enumerate(self.cells) if c['rect'][0]<=point[0]<=c['rect'][2] and c['rect'][1]<=point[1]<=c['rect'][3]),-1)
        if index>=0:self.active=index;self.picked.emit((index,point,self.mode))
        self.update()
    def mouseMoveEvent(self,event):
        if self.start is None:return
        if self.mode=='move':
            previous=self.point(self.end);current=self.point(event.position())
            self.dragged.emit([current[0]-previous[0],current[1]-previous[1]])
        self.end=event.position();self.update()
    def mouseReleaseEvent(self,event):
        if self.start is None:return
        if self.mode=='copy':
            a=self.point(self.start);b=self.point(event.position())
            if abs(a[0]-b[0])*self.target.width()>3 and abs(a[1]-b[1])*self.target.height()>3:
                self.copied.emit([min(a[0],b[0]),min(a[1],b[1]),max(a[0],b[0]),max(a[1],b[1])])
        self.start=None;self.end=None;self.finished.emit();self.update()
    def wheelEvent(self,event):
        if self.target.contains(event.position()) and self.mode=='move':
            self.zoomed.emit(event.angleDelta().y()/120);event.accept()
        else:event.ignore()


class CutEditor(QDialog):
    def __init__(self,entry,entries,icons,clipboard=None,parent=None):
        super().__init__(parent);self.setWindowTitle('컷 편집 · 분할하고 그림 붙여넣기');self.resize(1250,850)
        self.entry=entry;self.entries=entries;self.clipboard=clipboard
        self.composition=copy.deepcopy(entry.get('composition') or empty_composition())
        self.history=[];self.redo_history=[];self.gesture=None;self.assets_cache={};self.changed=False
        self.base=read_pixels(entry['path']);self.preview=self.base.copy();self.preview.thumbnail((1600,1600))
        root=QVBoxLayout(self);toolbar=QHBoxLayout();root.addLayout(toolbar)
        self.mode_buttons={}
        for name,label in [('move','배치 / 이동'),('vertical','세로 분할선'),('horizontal','가로 분할선'),('copy','영역 복사')]:
            button=QPushButton(label);button.setCheckable(True);button.clicked.connect(lambda checked,n=name:self.set_mode(n));toolbar.addWidget(button);self.mode_buttons[name]=button
        for label,fn in [('실행 취소',self.undo),('다시 실행',self.redo),('컷 배치 초기화',self.reset)]:
            button=QPushButton(label);button.clicked.connect(fn);toolbar.addWidget(button)
        split=QSplitter();root.addWidget(split,1)
        left=QWidget();ll=QVBoxLayout(left);ll.addWidget(QLabel('복사할 그림 선택 (현재 모자이크 포함)'))
        self.sources=QListWidget();self.sources.setIconSize(QSize(90,70));ll.addWidget(self.sources)
        for index,source in enumerate(entries):
            item=QListWidgetItem(icons[index],f'{index+1:03d}  {Path(source["path"]).name}');self.sources.addItem(item)
        copy_button=QPushButton('선택 그림 전체 복사');copy_button.clicked.connect(self.copy_source);ll.addWidget(copy_button)
        self.sources.itemDoubleClicked.connect(lambda item:self.copy_source())
        split.addWidget(left);self.canvas=PanelCanvas();split.addWidget(self.canvas);split.setSizes([270,900])
        self.canvas.picked.connect(self.pick);self.canvas.dragged.connect(self.move_layer);self.canvas.zoomed.connect(self.scale_layer)
        self.canvas.finished.connect(self.finish_gesture);self.canvas.copied.connect(self.copy_region)
        controls=QHBoxLayout();root.addLayout(controls)
        for label,fn in [('선택 컷에 붙여넣기',self.paste),('축소 −',lambda:self.scale_layer(-1)),('확대 +',lambda:self.scale_layer(1)),('컷에 꽉 맞춤',lambda:self.fit(True)),('그림 전체 맞춤',lambda:self.fit(False)),('붙인 그림 제거',self.remove_layer)]:
            button=QPushButton(label);button.clicked.connect(fn);controls.addWidget(button)
        self.info=QLabel();root.addWidget(self.info)
        gap_controls=QHBoxLayout();root.addLayout(gap_controls);gap_controls.addWidget(QLabel('컷 사이 흰 간격 (출력 픽셀)'))
        self.gutter=QSpinBox();self.gutter.setRange(0,min(200,self.base.width//10));self.gutter.setValue(round(self.composition.get('gutter',0.)*self.base.width))
        self.gutter.valueChanged.connect(self.change_gutter);gap_controls.addWidget(self.gutter);gap_controls.addStretch()
        self.help=QLabel('분할 도구 선택 → 그림을 클릭해 컷 나누기 · 컷 선택 → 붙여넣기 · 드래그: 그림 이동 / 휠: 붙인 그림 크기');root.addWidget(self.help)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('적용');buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('취소')
        buttons.accepted.connect(self.apply);buttons.rejected.connect(self.reject);root.addWidget(buttons)
        self.shortcuts=[]
        for sequence,fn in [('Ctrl+C',self.copy_source),('Ctrl+V',self.paste),('Ctrl+Z',self.undo),('Ctrl+Y',self.redo),('Ctrl+Shift+Z',self.redo)]:
            shortcut=QShortcut(QKeySequence(sequence),self);shortcut.activated.connect(fn);self.shortcuts.append(shortcut)
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(16);self.timer.timeout.connect(self.refresh)
        self.set_mode('move');self.refresh()
    def set_mode(self,mode):
        self.canvas.mode=mode
        for key,button in self.mode_buttons.items():button.setChecked(key==mode)
    def record(self):
        self.history.append(copy.deepcopy(self.composition));self.history=self.history[-200:];self.redo_history.clear()
    def update_image(self):
        if not self.timer.isActive():self.timer.start()
    def refresh(self):
        self.timer.stop()
        image=render_composition(self.preview,self.composition,self.assets_cache)
        image=render_clones(image,self.entry.get('clones',[]));image=render_regions(image,self.entry['regions'])
        rgba=image.convert('RGBA');qimage=QImage(rgba.tobytes(),rgba.width,rgba.height,rgba.width*4,QImage.Format.Format_RGBA8888).copy()
        self.canvas.pixmap=QPixmap.fromImage(qimage);self.canvas.cells=self.composition['cells']
        self.canvas.active=min(self.canvas.active,len(self.canvas.cells)-1);self.canvas.update()
        self.gutter.blockSignals(True);self.gutter.setValue(round(self.composition.get('gutter',0.)*self.base.width));self.gutter.blockSignals(False)
        self.info.setText(f'컷 {len(self.canvas.cells)}개 · 선택 {self.canvas.active+1}번 · '+('복사한 그림 있음' if self.clipboard else '그림을 복사한 뒤 붙여넣으세요'))
    def pick(self,event):
        index,point,mode=event;self.finish_gesture()
        if mode in ('vertical','horizontal'):
            cell=self.composition['cells'][index];rect=cell['rect'];axis=0 if mode=='vertical' else 1
            value=point[axis];lo,hi=rect[axis],rect[axis+2]
            if not lo+.02<value<hi-.02:return
            self.record();first=copy.deepcopy(cell);second=copy.deepcopy(cell)
            first['rect'][axis+2]=value;second['rect'][axis]=value
            self.composition['cells'][index:index+1]=[first,second];self.set_mode('move');self.refresh()
        elif mode=='move':self.gesture=copy.deepcopy(self.composition);self.update_image()
    def change_gutter(self,value):
        self.record();self.composition['gutter']=value/self.base.width;self.refresh()
    def finish_gesture(self):
        if self.gesture is not None and self.gesture!=self.composition:
            self.history.append(self.gesture);self.history=self.history[-200:];self.redo_history.clear()
        self.gesture=None
    def cell(self):return self.composition['cells'][self.canvas.active]
    def copy_source(self):
        row=self.sources.currentRow()
        if row<0:return
        try:
            source=self.entries[row];image=render_entry(read_pixels(source['path']),source)
            self.clipboard=pixel_asset(image);self.set_mode('move');self.refresh()
        except Exception as exc:QMessageBox.warning(self,'복사 실패',str(exc))
    def copy_region(self,rect):
        try:
            draft=dict(self.entry,composition=self.composition);image=render_entry(self.base,draft)
            box=(round(rect[0]*image.width),round(rect[1]*image.height),round(rect[2]*image.width),round(rect[3]*image.height))
            if box[2]>box[0] and box[3]>box[1]:self.clipboard=pixel_asset(image.crop(box))
            self.set_mode('move');self.refresh()
        except Exception as exc:QMessageBox.warning(self,'복사 실패',str(exc))
    def paste(self):
        if not self.clipboard:self.info.setText('먼저 왼쪽 그림을 선택하고 복사하세요.');return
        self.record();key,data=self.clipboard;self.composition['assets'][key]=data
        self.cell().update(asset=key,scale=1.,offset=[0.,0.]);self.set_mode('move');self.refresh()
    def move_layer(self,delta):
        cell=self.cell()
        if 'asset' not in cell:return
        x1,y1,x2,y2=cell['rect'];ox,oy=cell.get('offset',[0.,0.])
        cell['offset']=[max(-100.,min(100.,ox+delta[0]/(x2-x1))),max(-100.,min(100.,oy+delta[1]/(y2-y1)))];self.update_image()
    def scale_layer(self,steps):
        cell=self.cell()
        if 'asset' not in cell or not steps:return
        value=max(.05,min(32.,cell.get('scale',1.)*1.15**steps))
        if value==cell.get('scale',1.):return
        self.finish_gesture();self.record();cell['scale']=value;self.refresh()
    def fit(self,cover):
        cell=self.cell()
        if 'asset' not in cell:return
        self.record();source=self.assets_cache[cell['asset']];x1,y1,x2,y2=cell['rect']
        w,h=(x2-x1)*self.base.width,(y2-y1)*self.base.height
        cell['scale']=1. if cover else max(.05,min(32.,min(w/source.width,h/source.height)/max(w/source.width,h/source.height)))
        cell['offset']=[0.,0.];self.refresh()
    def remove_layer(self):
        if 'asset' not in self.cell():return
        self.record();self.composition['cells'][self.canvas.active]={'rect':self.cell()['rect'][:]};self.refresh()
    def reset(self):
        self.record();self.composition=empty_composition();self.canvas.active=0;self.refresh()
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
        self.accept()
