from PySide6.QtCore import QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QDialogButtonBox,QCheckBox,QLineEdit,QComboBox,QSpinBox,QTabWidget
from cut_editor import SourceCanvas,ImageCanvas
from imaging import read_pixels,render_entry,crop_box
from banner_text import DEFAULT_TEXT,FONTS,POSITIONS,render_banner_text


class BannerPreview(ImageCanvas):
    def paintEvent(self,event):
        painter=QPainter(self);self.paint_image(painter)
    def wheelEvent(self,event):self.zoom_view(event)
    def mousePressEvent(self,event):self.begin_pan(event)
    def mouseMoveEvent(self,event):self.continue_pan(event)
    def mouseReleaseEvent(self,event):self.end_pan(event)


class BannerEditor(QDialog):
    def __init__(self,entry,parent=None,total_count=0):
        super().__init__(parent);self.setWindowTitle('배너 영역과 문구');self.resize(1000,800);self.total_count=total_count
        self.image=render_entry(read_pixels(entry['path']),entry)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('드래그로 영역 선택 · 모서리로 조절 · 휠: 확대 · Ctrl+드래그: 이동'))
        options=dict(DEFAULT_TEXT,**entry.get('banner_text',{}))
        row=QHBoxLayout();layout.addLayout(row)
        self.text_enabled=QCheckBox('문구 넣기');self.text_enabled.setChecked(options['enabled']);row.addWidget(self.text_enabled)
        row.addWidget(QLabel(f'현재 작업 {total_count}장 · {{count}}는 출력할 때 자동 계산'));row.addStretch()
        self.font=QComboBox()
        for key,(_,label) in FONTS.items():self.font.addItem(label,key)
        self.font.setCurrentIndex(self.font.findData(options['font']));row.addWidget(self.font)
        row.addWidget(QLabel('크기 %'));self.text_size=QSpinBox();self.text_size.setRange(2,25);self.text_size.setValue(round(options['size']*100));row.addWidget(self.text_size)
        self.position=QComboBox()
        for key,label in POSITIONS.items():self.position.addItem(label,key)
        self.position.setCurrentIndex(self.position.findData(options['position']));row.addWidget(self.position)
        row=QHBoxLayout();layout.addLayout(row)
        row.addWidget(QLabel('윗줄'));self.ja=QLineEdit(options['ja']);self.ja.setMaxLength(200);row.addWidget(self.ja)
        row.addWidget(QLabel('아랫줄'));self.en=QLineEdit(options['en']);self.en.setMaxLength(200);row.addWidget(self.en)
        self.tabs=QTabWidget();layout.addWidget(self.tabs,1)
        self.canvas=SourceCanvas();preview=self.image.copy();preview.thumbnail((1800,1800));self.canvas.set_image(preview)
        self.canvas.selection=entry.get('banner_rect',[0.,0.,1.,1.])[:];self.tabs.addTab(self.canvas,'영역 선택')
        self.preview=BannerPreview();self.tabs.addTab(self.preview,'출력 미리보기')
        self.info=QLabel();layout.addWidget(self.info)
        self.preview_timer=QTimer(self);self.preview_timer.setSingleShot(True);self.preview_timer.setInterval(100);self.preview_timer.timeout.connect(self.refresh_preview)
        self.canvas.selectionChanged.connect(self.update_info)
        for signal in (self.text_enabled.toggled,self.font.currentIndexChanged,self.text_size.valueChanged,self.position.currentIndexChanged,self.ja.textChanged,self.en.textChanged):signal.connect(self.schedule_preview)
        self.tabs.currentChanged.connect(lambda index:self.refresh_preview() if index==1 else None)
        self.update_info();self.refresh_preview()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('배너로 지정');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)
        self.finished.connect(lambda:self.preview_timer.stop())

    def selection(self):return self.canvas.selection or [0.,0.,1.,1.]

    def text_options(self):
        return {'enabled':self.text_enabled.isChecked(),'ja':self.ja.text(),'en':self.en.text(),'font':self.font.currentData(),'size':self.text_size.value()/100,'position':self.position.currentData()}

    def schedule_preview(self,*args):self.preview_timer.start()

    def update_info(self,*args):
        x1,y1,x2,y2=crop_box(self.image,self.selection())
        self.info.setText(f'출력 {x2-x1} × {y2-y1}px · 편집과 모자이크 반영 · PNG로 저장 · 원본 그림은 유지')
        self.schedule_preview()

    def refresh_preview(self):
        self.preview_timer.stop();image=self.image.crop(crop_box(self.image,self.selection()));image.thumbnail((1600,1600))
        self.preview.set_image(render_banner_text(image,self.text_options(),self.total_count))
