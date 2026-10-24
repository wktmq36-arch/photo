from PySide6.QtCore import Qt,Signal,QTimer
from PySide6.QtGui import QPainter,QKeySequence,QShortcut
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSpinBox,QCheckBox,QStackedWidget
from cut_editor import SourceCanvas,ImageCanvas
from imaging import read_pixels,render_entry,crop_box,cover_box,cover_crop


class CropPreview(ImageCanvas):
    reframed=Signal(object)
    def __init__(self):
        super().__init__();self.drag_start=None
    def paintEvent(self,event):
        painter=QPainter(self);self.paint_image(painter)
    def wheelEvent(self,event):self.zoom_view(event)
    def mousePressEvent(self,event):
        if self.begin_pan(event):return
        if event.button()==Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            self.drag_start=event.position();self.setCursor(Qt.CursorShape.ClosedHandCursor)
    def mouseMoveEvent(self,event):
        if self.continue_pan(event):return
        if self.drag_start is not None:
            delta=event.position()-self.drag_start;self.drag_start=event.position()
            self.reframed.emit([delta.x()/self.target.width(),delta.y()/self.target.height()])
    def mouseReleaseEvent(self,event):
        if self.end_pan(event):return
        self.drag_start=None;self.unsetCursor()


class CropEditor(QWidget):
    accepted=Signal();rejected=Signal()
    def __init__(self,entry,parent=None):
        super().__init__(parent)
        previous=entry.get('crop_source')
        self.replacing=bool(previous and not entry.get('regions') and not entry.get('clones') and not entry.get('erasers') and not entry.get('composition'))
        self.image=render_entry(read_pixels(entry['path']),previous['edits'] if self.replacing else entry)
        self.anchor=list(previous.get('anchor',[.5,.5])) if self.replacing else [.5,.5]
        self.initial_rect=list(previous['rect']) if self.replacing else [0.,0.,1.,1.];self.initial_anchor=self.anchor[:]
        self.initial_mode=previous.get('mode','stretch') if self.replacing else 'cover'
        w,h=self.image.size;self.preview_size=self.image.copy();self.preview_size.thumbnail((1800,1800));self.preview_size=self.preview_size.size
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        title=QLabel(f'사진 자르기 → 비율 유지 확대 · 출력 {w} × {h}px (넘치는 부분은 잘림)')
        title.setStyleSheet('font-weight:bold;padding:4px;');root.addWidget(title)
        controls=QHBoxLayout();root.addLayout(controls);self.trims={}
        for key,label,limit in [('top','위',h-1),('bottom','아래',h-1),('left','왼쪽',w-1),('right','오른쪽',w-1)]:
            controls.addWidget(QLabel(label));number=QSpinBox();number.setRange(0,limit);number.setSuffix(' px');number.setFixedWidth(100)
            number.setKeyboardTracking(False);self.trims[key]=number;controls.addWidget(number)
            number.valueChanged.connect(self.trim_changed)
        controls.addStretch();self.result_check=QCheckBox('확대 결과 보기 · 드래그로 구도 조절');controls.addWidget(self.result_check)
        self.pages=QStackedWidget();root.addWidget(self.pages,1)
        self.source=SourceCanvas();self.pages.addWidget(self.source)
        self.preview=CropPreview();self.pages.addWidget(self.preview)
        source_preview=self.image.copy();source_preview.thumbnail((1800,1800));self.source.set_image(source_preview,True)
        self.source.selectionChanged.connect(self.selection_changed)
        self.result_check.toggled.connect(self.show_result)
        self.preview.reframed.connect(self.reframe)
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(16);self.preview_timer.timeout.connect(self.refresh_preview)
        self.info=QLabel();self.info.setWordWrap(True);root.addWidget(self.info)
        buttons=QHBoxLayout();root.addLayout(buttons)
        for label,fn in [('선택 초기화',self.reset_selection),('구도 중앙',self.center_frame),('화면 맞춤',self.reset_view)]:
            button=QPushButton(label);button.clicked.connect(fn);buttons.addWidget(button)
        buttons.addStretch()
        apply=QPushButton('비율 유지 확대 적용');apply.clicked.connect(self.accepted.emit);apply.setStyleSheet('background:#287fce;color:white;font-weight:bold;padding:8px;');buttons.addWidget(apply)
        cancel=QPushButton('취소');cancel.clicked.connect(self.rejected.emit);buttons.addWidget(cancel)
        for number in self.trims.values():number.lineEdit().returnPressed.connect(self.source.setFocus)
        self.escape=QShortcut(QKeySequence('Escape'),self);self.escape.activated.connect(self.rejected.emit)
        if self.replacing:self.source.selection=self.initial_rect[:]
        self.selection_changed(None)
    def rect(self):
        return list(self.source.selection or [0.,0.,1.,1.])
    def has_changes(self):
        return crop_box(self.image,self.rect())!=crop_box(self.image,self.initial_rect) or self.anchor!=self.initial_anchor or self.initial_mode!='cover'
    def selection_changed(self,rect):
        w,h=self.image.size;left,top,right,bottom=crop_box(self.image,self.rect())
        values={'left':left,'top':top,'right':w-right,'bottom':h-bottom}
        for number in self.trims.values():number.blockSignals(True)
        for key,other,dimension in [('left','right',w),('right','left',w),('top','bottom',h),('bottom','top',h)]:
            self.trims[key].setRange(0,dimension-1-values[other]);self.trims[key].setValue(values[key])
        for number in self.trims.values():number.blockSignals(False)
        self.info.setText(f'선택 {right-left} × {bottom-top}px → 출력 {w} × {h}px · 같은 배율로 확대하여 넘치는 부분만 자릅니다. 확대 결과에서 드래그로 구도를 조절하세요.')
        if self.result_check.isChecked():self.refresh_preview()
    def trim_changed(self,*args):
        w,h=self.image.size
        self.source.selection=[self.trims['left'].value()/w,self.trims['top'].value()/h,1-self.trims['right'].value()/w,1-self.trims['bottom'].value()/h]
        self.source.update();self.selection_changed(self.source.selection)
    def refresh_preview(self):
        self.preview_timer.stop()
        result=cover_crop(self.image,self.rect(),self.anchor,self.preview_size)
        self.preview.set_image(result)
    def reframe(self,delta):
        left,top,right,bottom=crop_box(self.image,self.rect());box=cover_box(self.image,self.rect(),self.anchor)
        visible=[box[2]-box[0],box[3]-box[1]];overflow=[right-left-visible[0],bottom-top-visible[1]]
        for axis in (0,1):
            if overflow[axis]>1e-6:self.anchor[axis]=max(0.,min(1.,self.anchor[axis]-delta[axis]*visible[axis]/overflow[axis]))
        if not self.preview_timer.isActive():self.preview_timer.start()
    def center_frame(self):
        self.anchor=[.5,.5]
        if self.result_check.isChecked():self.refresh_preview()
    def reset_selection(self):
        self.anchor=[.5,.5];self.source.clear_selection()
    def show_result(self,enabled):
        if enabled:self.refresh_preview()
        self.pages.setCurrentWidget(self.preview if enabled else self.source)
    def reset_view(self):self.source.reset_view();self.preview.reset_view()
