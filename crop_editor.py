from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QPainter,QKeySequence,QShortcut
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QSpinBox,QCheckBox,QStackedWidget
from cut_editor import SourceCanvas,ImageCanvas
from imaging import read_pixels,render_entry,crop_box
from PIL import Image


class CropPreview(ImageCanvas):
    def paintEvent(self,event):
        painter=QPainter(self);self.paint_image(painter)
    def wheelEvent(self,event):self.zoom_view(event)
    def mousePressEvent(self,event):self.begin_pan(event)
    def mouseMoveEvent(self,event):self.continue_pan(event)
    def mouseReleaseEvent(self,event):self.end_pan(event)


class CropEditor(QWidget):
    accepted=Signal();rejected=Signal()
    def __init__(self,entry,parent=None):
        super().__init__(parent)
        self.image=render_entry(read_pixels(entry['path']),entry)
        w,h=self.image.size;self.preview_size=self.image.copy();self.preview_size.thumbnail((1800,1800));self.preview_size=self.preview_size.size
        root=QVBoxLayout(self);root.setContentsMargins(0,0,0,0)
        title=QLabel(f'사진 자르기 → 남은 부분 전체를 {w} × {h}px로 늘리기 (흰 여백 없음)')
        title.setStyleSheet('font-weight:bold;padding:4px;');root.addWidget(title)
        controls=QHBoxLayout();root.addLayout(controls);self.trims={}
        for key,label,limit in [('top','위',h-1),('bottom','아래',h-1),('left','왼쪽',w-1),('right','오른쪽',w-1)]:
            controls.addWidget(QLabel(label));number=QSpinBox();number.setRange(0,limit);number.setSuffix(' px');number.setFixedWidth(100)
            number.setKeyboardTracking(False);self.trims[key]=number;controls.addWidget(number)
            number.valueChanged.connect(self.trim_changed)
        controls.addStretch();self.result_check=QCheckBox('자른 뒤 결과 보기');controls.addWidget(self.result_check)
        self.pages=QStackedWidget();root.addWidget(self.pages,1)
        self.source=SourceCanvas();self.pages.addWidget(self.source)
        self.preview=CropPreview();self.pages.addWidget(self.preview)
        source_preview=self.image.copy();source_preview.thumbnail((1800,1800));self.source.set_image(source_preview,True)
        self.source.selectionChanged.connect(self.selection_changed)
        self.result_check.toggled.connect(self.show_result)
        self.info=QLabel();root.addWidget(self.info)
        buttons=QHBoxLayout();root.addLayout(buttons)
        for label,fn in [('선택 초기화',self.source.clear_selection),('화면 맞춤',self.reset_view)]:
            button=QPushButton(label);button.clicked.connect(fn);buttons.addWidget(button)
        buttons.addStretch()
        apply=QPushButton('자른 뒤 원래 크기로 늘리기');apply.clicked.connect(self.accepted.emit);apply.setStyleSheet('background:#287fce;color:white;font-weight:bold;padding:8px;');buttons.addWidget(apply)
        cancel=QPushButton('취소');cancel.clicked.connect(self.rejected.emit);buttons.addWidget(cancel)
        for number in self.trims.values():number.lineEdit().returnPressed.connect(self.source.setFocus)
        self.escape=QShortcut(QKeySequence('Escape'),self);self.escape.activated.connect(self.rejected.emit)
        self.selection_changed(None)
    def rect(self):
        return list(self.source.selection or [0.,0.,1.,1.])
    def has_changes(self):return crop_box(self.image,self.rect())!=(0,0,self.image.width,self.image.height)
    def selection_changed(self,rect):
        w,h=self.image.size;left,top,right,bottom=crop_box(self.image,self.rect())
        values={'left':left,'top':top,'right':w-right,'bottom':h-bottom}
        for number in self.trims.values():number.blockSignals(True)
        for key,other,dimension in [('left','right',w),('right','left',w),('top','bottom',h),('bottom','top',h)]:
            self.trims[key].setRange(0,dimension-1-values[other]);self.trims[key].setValue(values[key])
        for number in self.trims.values():number.blockSignals(False)
        self.info.setText(f'남길 영역 {right-left} × {bottom-top}px → 결과 {w} × {h}px · 비율이 달라도 선택 전체 유지 · 드래그/모서리로 범위 조절')
        if self.result_check.isChecked():self.refresh_preview()
    def trim_changed(self,*args):
        w,h=self.image.size
        self.source.selection=[self.trims['left'].value()/w,self.trims['top'].value()/h,1-self.trims['right'].value()/w,1-self.trims['bottom'].value()/h]
        self.source.update();self.selection_changed(self.source.selection)
    def refresh_preview(self):
        result=self.image.crop(crop_box(self.image,self.rect())).resize(self.preview_size,Image.Resampling.LANCZOS)
        self.preview.set_image(result)
    def show_result(self,enabled):
        if enabled:self.refresh_preview()
        self.pages.setCurrentWidget(self.preview if enabled else self.source)
    def reset_view(self):self.source.reset_view();self.preview.reset_view()
