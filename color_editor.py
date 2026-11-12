from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QSpinBox, QVBoxLayout)
from pathlib import Path

from color_adjust import encode_mask, render_colors, wand_mask
from cut_editor import SourceCanvas
from imaging import read_pixels, render_entry


class ColorCanvas(SourceCanvas):
    def __init__(self, pick):
        super().__init__()
        self.pick = pick
        self.wand = True
        self.redraw_on_drag = True

    def mousePressEvent(self, event):
        if (self.wand and self.pixmap and event.button() == Qt.MouseButton.LeftButton
                and not event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.update_target()
            if self.target.contains(event.position()):
                self.pick(self.point(event.position()))
            return
        super().mousePressEvent(event)


class ColorEditor(QDialog):
    def __init__(self, entry, entries, parent):
        super().__init__(parent)
        self.setWindowTitle('선택 영역 색 조절')
        self.resize(1150, 750)
        self.image = self.preview(entry)
        self.seed = None
        self.selected = None
        self.mask = None
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        self.mode = QComboBox()
        self.mode.addItems(['마법봉', '사각형'])
        controls.addWidget(self.mode)
        self.tolerance = self.number(controls, '색 허용 범위', 0, 255, 32)
        self.hue = self.number(controls, '색상 °', -180, 180)
        self.saturation = self.number(controls, '채도', -100, 100)
        self.value = self.number(controls, '명도', -100, 100)
        self.guide = QLabel('눈 안쪽을 클릭해 이어진 비슷한 색을 선택하세요.')
        layout.addWidget(self.guide)
        views = QHBoxLayout()
        layout.addLayout(views, 1)
        self.canvas = ColorCanvas(self.pick)
        self.canvas.set_image(self.image)
        views.addWidget(self.canvas, 1)
        reference = QVBoxLayout()
        views.addLayout(reference, 1)
        self.pages = QComboBox()
        self.pages.addItem('비교할 페이지 선택')
        for index, page in enumerate(entries, 1):
            self.pages.addItem(f'{index:03d}  {Path(page["path"]).name}', page)
        reference.addWidget(self.pages)
        self.reference = SourceCanvas()
        reference.addWidget(self.reference, 1)
        self.pages.currentIndexChanged.connect(self.load_reference)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText('색 조절 적용')
        self.apply_button.setEnabled(False)
        layout.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.timer = QTimer(self, singleShot=True, interval=40)
        self.timer.timeout.connect(self.refresh)
        self.mode.currentIndexChanged.connect(self.change_mode)
        self.canvas.selectionChanged.connect(self.rectangle_selected)
        self.tolerance.valueChanged.connect(self.reselect)
        for control in (self.hue, self.saturation, self.value):
            control.valueChanged.connect(lambda: self.timer.start())

    @staticmethod
    def number(layout, label, minimum, maximum, value=0):
        layout.addWidget(QLabel(label))
        control = QSpinBox()
        control.setRange(minimum, maximum)
        control.setValue(value)
        layout.addWidget(control)
        return control

    @staticmethod
    def preview(entry):
        image = render_entry(read_pixels(entry['path']), entry)
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        return image

    def load_reference(self):
        entry = self.pages.currentData()
        try:
            self.reference.set_image(self.preview(entry) if entry else None, reset=True)
        except (OSError, ValueError) as error:
            self.reference.set_image(None)
            self.guide.setText(str(error))

    def change_mode(self, index):
        self.canvas.wand = index == 0
        self.seed = None
        self.canvas.clear_selection()
        self.tolerance.setEnabled(self.canvas.wand)
        self.guide.setText('눈 안쪽을 클릭해 이어진 비슷한 색을 선택하세요.' if self.canvas.wand else '드래그해 색을 조절할 사각형을 그리세요.')

    def pick(self, point):
        self.seed = tuple(min(size - 1, int(v * size)) for v, size in zip(point, self.image.size))
        self.reselect()

    def reselect(self):
        if self.seed is None:
            return
        mask = wand_mask(self.image, self.seed, self.tolerance.value())
        box = mask.getbbox()
        if box is None:
            return
        self.selected = [v / self.image.size[i % 2] for i, v in enumerate(box)]
        self.mask = encode_mask(mask.crop(box))
        overlay = self.image.copy()
        overlay.paste((35, 150, 255, 255), (0, 0, *self.image.size), mask.point(lambda v: v // 3))
        self.canvas.set_image(overlay)
        self.apply_button.setEnabled(any(c.value() for c in (self.hue, self.saturation, self.value)))
        if self.apply_button.isEnabled():
            self.timer.start()

    def rectangle_selected(self, rect):
        self.selected = rect
        self.mask = None
        self.refresh()

    def adjustment(self):
        if not self.selected or not any(c.value() for c in (self.hue, self.saturation, self.value)):
            return None
        edit = dict(rect=self.selected, hue=self.hue.value(), saturation=self.saturation.value(), value=self.value.value())
        if self.mask is not None:
            edit['mask'] = self.mask
        return edit

    def refresh(self):
        edit = self.adjustment()
        self.apply_button.setEnabled(edit is not None)
        self.canvas.set_image(render_colors(self.image, [edit]) if edit else self.image)
