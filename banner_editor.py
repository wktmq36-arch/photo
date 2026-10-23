from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QDialogButtonBox
from cut_editor import SourceCanvas
from imaging import read_pixels,render_entry,crop_box


class BannerEditor(QDialog):
    def __init__(self,entry,parent=None):
        super().__init__(parent);self.setWindowTitle('배너 영역 선택');self.resize(1000,750)
        self.image=render_entry(read_pixels(entry['path']),entry)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('드래그로 영역 선택 · 모서리로 조절 · 휠: 확대 · Ctrl+드래그: 이동'))
        self.canvas=SourceCanvas();preview=self.image.copy();preview.thumbnail((1800,1800));self.canvas.set_image(preview)
        self.canvas.selection=entry.get('banner_rect',[0.,0.,1.,1.])[:];layout.addWidget(self.canvas,1)
        self.info=QLabel();layout.addWidget(self.info);self.canvas.selectionChanged.connect(self.update_info);self.update_info()
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('배너로 지정');buttons.accepted.connect(self.accept);buttons.rejected.connect(self.reject);layout.addWidget(buttons)

    def selection(self):return self.canvas.selection or [0.,0.,1.,1.]

    def update_info(self,*args):
        x1,y1,x2,y2=crop_box(self.image,self.selection())
        self.info.setText(f'출력 {x2-x1} × {y2-y1}px · 편집과 모자이크 반영 · PNG로 저장 · 원본 그림은 유지')
