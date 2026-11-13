from PIL import Image, ImageChops, ImageFilter
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout)
from pathlib import Path

from color_adjust import encode_mask, render_colors, tonal_palette, wand_mask
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
                modifiers = event.modifiers()
                self.pick(self.point(event.position()),
                          add=bool(modifiers & Qt.KeyboardModifier.ShiftModifier),
                          subtract=bool(modifiers & Qt.KeyboardModifier.AltModifier))
            return
        super().mousePressEvent(event)


class ColorEditor(QDialog):
    def __init__(self, entry, entries, parent, thumbnails=None):
        super().__init__(parent)
        self.setWindowTitle('선택 영역 색 조절')
        self.resize(1150, 750)
        self.settings = getattr(parent, 'settings', None)
        self.image = self.preview(entry)
        self.seeds = []
        self.palette = None
        self.target_mask = None
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
        self.guide = QLabel('클릭: 새 선택 · Shift+클릭: 추가 · Alt+클릭: 빼기')
        layout.addWidget(self.guide)
        views = QHBoxLayout()
        layout.addLayout(views, 1)
        self.canvas = ColorCanvas(self.pick)
        self.canvas.set_image(self.image)
        target = QVBoxLayout()
        views.addLayout(target, 1)
        self.show_result = QCheckBox('보정 후 미리보기')
        self.show_result.setChecked(True)
        target.addWidget(self.show_result)
        target.addWidget(self.canvas, 1)
        reference = QVBoxLayout()
        views.addLayout(reference, 1)
        self.entries = entries
        self.thumbnails = thumbnails
        self.reference_image = None
        self.reference_mask = None
        self.reference_seeds = []
        self.selection_history = []
        self.undo_selection_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_selection_shortcut.activated.connect(self.undo_selection)
        reference.addWidget(QLabel('비교 페이지 · 마법봉 · Shift+클릭: 추가 · Alt+클릭: 빼기'))
        self.pages = QListWidget()
        self.pages.setViewMode(QListWidget.ViewMode.IconMode)
        self.pages.setMovement(QListWidget.Movement.Static)
        self.pages.setWrapping(False)
        self.pages.setIconSize(QSize(60, 64))
        self.pages.setGridSize(QSize(82, 90))
        self.pages.setFixedHeight(110)
        for index, page in enumerate(entries):
            item = QListWidgetItem(f'{index + 1:03d}')
            item.setToolTip(Path(page['path']).name)
            if thumbnails is not None:
                item.setIcon(thumbnails.item(index).icon())
            self.pages.addItem(item)
        if thumbnails is not None:
            thumbnails.itemChanged.connect(self.update_thumbnail)
        reference.addWidget(self.pages)
        self.reference = ColorCanvas(self.pick_reference)
        reference.addWidget(self.reference, 1)
        self.pages.currentRowChanged.connect(self.load_reference)
        self.match_button = QPushButton('기준 색에 맞추기')
        self.match_button.setEnabled(False)
        self.match_button.clicked.connect(self.match_reference)
        reference.addWidget(self.match_button)
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
        self.tolerance.valueChanged.connect(self.refresh_reference)
        for control in (self.hue, self.saturation, self.value):
            control.valueChanged.connect(lambda: self.timer.start())
        self.show_result.toggled.connect(self.refresh)
        if self.settings is not None:
            geometry = self.settings.value('colorEditor/geometry')
            if geometry is not None:
                self.restoreGeometry(geometry)
            for key, control in self.number_options():
                control.setValue(self.settings.value('colorEditor/' + key, control.value(), type=int))
            self.mode.setCurrentIndex(self.settings.value('colorEditor/mode', 0, type=int))
            self.show_result.setChecked(self.settings.value('colorEditor/showResult', True, type=bool))
            self.finished.connect(self.save_options)

    def number_options(self):
        return (('tolerance', self.tolerance), ('hue', self.hue),
                ('saturation', self.saturation), ('value', self.value))

    def save_options(self):
        self.settings.setValue('colorEditor/geometry', self.saveGeometry())
        self.settings.setValue('colorEditor/mode', self.mode.currentIndex())
        self.settings.setValue('colorEditor/showResult', self.show_result.isChecked())
        for key, control in self.number_options():
            self.settings.setValue('colorEditor/' + key, control.value())


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

    def update_thumbnail(self, item):
        row = self.thumbnails.row(item)
        if 0 <= row < self.pages.count():
            self.pages.item(row).setIcon(item.icon())

    def load_reference(self, row):
        self.palette = None
        self.reference_image = None
        self.reference_mask = None
        self.reference_seeds.clear()
        self.selection_history = [step for step in self.selection_history if not step[0]]
        self.match_button.setEnabled(False)
        try:
            if row >= 0:
                self.reference_image = self.preview(self.entries[row])
            self.reference.set_image(self.reference_image, reset=True)
        except (OSError, ValueError) as error:
            self.reference.set_image(None)
            self.guide.setText(str(error))
        self.refresh()

    def pick_reference(self, point, add=False, subtract=False):
        if self.reference_image is None:
            return
        self.select_seed(self.seed_at(self.reference_image, point), add, reference=True, subtract=subtract)

    def select_seed(self, seed, add, reference=False, subtract=False):
        seeds = self.reference_seeds if reference else self.seeds
        operation = (seed, subtract)
        if subtract and not seeds:
            return
        updated = [*seeds, operation] if add or subtract else [operation]
        if updated == seeds:
            return
        self.selection_history.append((reference, seeds[:]))
        seeds[:] = updated
        (self.refresh_reference if reference else self.reselect)()

    def undo_selection(self):
        if not self.selection_history:
            return
        reference, previous = self.selection_history.pop()
        seeds = self.reference_seeds if reference else self.seeds
        seeds[:] = previous
        (self.refresh_reference if reference else self.reselect)()

    def restore_reference_selection(self, saved):
        if self.reference_image is None or not isinstance(saved, list):
            return
        width, height = self.reference_image.size
        for operation in saved:
            if not isinstance(operation, (list, tuple)) or len(operation) != 2:
                continue
            seed, subtract = operation
            if (isinstance(seed, (list, tuple)) and len(seed) == 2
                    and type(seed[0]) is int and type(seed[1]) is int
                    and 0 <= seed[0] < width and 0 <= seed[1] < height
                    and type(subtract) is bool):
                self.reference_seeds.append((tuple(seed), subtract))
        self.refresh_reference()

    def refresh_reference(self):
        self.palette = None
        self.refresh()
        if not self.reference_seeds:
            self.reference_mask = None
            self.reference.set_image(self.reference_image)
            self.match_button.setEnabled(False)
            return
        image = self.reference_image
        self.reference_mask = self.combined_mask(image, self.reference_seeds)
        if not self.reference_mask.getbbox():
            self.reference_mask = None
        self.reference.set_image(self.highlight(image, self.reference_mask) if self.reference_mask else image)
        self.match_button.setEnabled(bool(self.selected) and self.reference_mask is not None)

    @staticmethod
    def seed_at(image, point):
        return tuple(min(size - 1, int(v * size)) for v, size in zip(point, image.size))

    def combined_mask(self, image, seeds):
        mask = Image.new('L', image.size)
        for seed, subtract in seeds:
            region = wand_mask(image, seed, self.tolerance.value())
            mask = ImageChops.subtract(mask, region) if subtract else ImageChops.lighter(mask, region)
        return mask

    @staticmethod
    def highlight(image, mask):
        overlay = image.copy()
        overlay.paste((35, 150, 255, 255), (0, 0, *image.size), mask.point(lambda v: v // 3))
        return overlay

    def match_reference(self):
        if not self.selected or self.reference_mask is None:
            return
        from imaging import crop_box
        box = crop_box(self.image, self.selected)
        patch = self.image.crop(box).convert('RGB')
        mask = self.target_mask.crop(box) if self.target_mask is not None else None
        self.palette = tonal_palette(patch, mask, self.reference_image, self.reference_mask)
        for control in (self.hue, self.saturation, self.value):
            control.setValue(0)
        self.refresh()

    def change_mode(self, index):
        self.canvas.wand = index == 0
        self.seeds.clear()
        self.selection_history = [step for step in self.selection_history if step[0]]
        self.canvas.clear_selection()
        self.tolerance.setEnabled(True)
        self.guide.setText('클릭: 새 선택 · Shift+클릭: 추가 · Alt+클릭: 빼기' if self.canvas.wand else '드래그해 색을 조절할 사각형을 그리세요.')

    def pick(self, point, add=False, subtract=False):
        self.select_seed(self.seed_at(self.image, point), add, subtract=subtract)

    def reselect(self):
        self.palette = None
        if not self.seeds:
            self.target_mask = None
            self.selected = None
            self.mask = None
            self.refresh()
            return
        mask = self.combined_mask(self.image, self.seeds)
        box = mask.getbbox()
        if box is None:
            self.rectangle_selected(None)
            return
        self.selected = [v / self.image.size[i % 2] for i, v in enumerate(box)]
        self.mask = encode_mask(mask.crop(box))
        self.target_mask = mask
        self.refresh()

    def rectangle_selected(self, rect):
        self.palette = None
        self.selected = rect
        self.target_mask = None
        self.mask = None
        self.refresh()

    def adjustment(self):
        if not self.selected or (self.palette is None and not any(c.value() for c in (self.hue, self.saturation, self.value))):
            return None
        edit = dict(rect=self.selected, hue=self.hue.value(), saturation=self.saturation.value(), value=self.value.value())
        if self.mask is not None:
            edit['mask'] = self.mask
        if self.palette is not None:
            edit['palette'] = self.palette
        return edit

    def refresh(self):
        edit = self.adjustment()
        self.apply_button.setEnabled(edit is not None)
        self.match_button.setEnabled(bool(self.selected) and self.reference_mask is not None)
        self.canvas.show_selection = edit is None
        image = self.image
        if edit is not None and self.show_result.isChecked():
            image = render_colors(image, [edit])
        if edit is None and self.target_mask is not None:
            edge = ImageChops.subtract(self.target_mask, self.target_mask.filter(ImageFilter.MinFilter(3)))
            image = image.copy()
            image.paste((255, 179, 71, 255), (0, 0, *image.size), edge)
        self.canvas.set_image(image)
