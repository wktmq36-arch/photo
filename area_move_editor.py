from PIL import ImageChops, ImageFilter
from color_adjust import encode_mask, wand_mask
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QWidget, QHBoxLayout,
                               QLabel, QPushButton, QSpinBox, QVBoxLayout)

from area_moves import render_moves, selection_patch
from cut_editor import CutSourceCanvas


class MoveCanvas(CutSourceCanvas):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.drag_start = None
        self.redraw_on_drag = True
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event):
        if self.editor.moving and event.button() == Qt.MouseButton.LeftButton:
            if self.begin_pan(event):
                return
            self.drag_start = event.position()
            self.initial_offset = self.editor.offset[:]
            return
        if self.editor.shape.currentIndex() == 2 and not self.editor.moving:
            if self.begin_pan(event):
                return
            if event.button() == Qt.MouseButton.LeftButton and self.pixmap and self.target.contains(event.position()):
                self.editor.pick(self.point(event.position()), event.modifiers())
            return
        if event.button() == Qt.MouseButton.LeftButton and not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.editor.before_drag = self.editor.selection_state()
            self.editor.subtract_drag = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        super().mousePressEvent(event)

    directions = {Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
                  Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1)}

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride and self.editor.moving and event.key() in self.directions:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if self.editor.moving and event.key() in self.directions:
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = self.directions[event.key()]
            self.editor.nudge(dx * step, dy * step)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_start is None:
            return super().mouseMoveEvent(event)
        delta = event.position() - self.drag_start
        self.editor.offset = [
            max(-1., min(1., start + change / max(1, extent)))
            for start, change, extent in zip(self.initial_offset, (delta.x(), delta.y()),
                                              (self.target.width(), self.target.height()))
        ]
        if not self.editor.timer.isActive():
            self.editor.timer.start()

    def mouseReleaseEvent(self, event):
        if self.drag_start is None:
            return super().mouseReleaseEvent(event)
        self.mouseMoveEvent(event)
        self.drag_start = None
        self.editor.refresh()


class AreaMoveEditor(QWidget):
    def __init__(self, parent, commit):
        super().__init__(parent)
        self.commit = commit
        self.image = None
        self.moving = False
        self.offset = [0., 0.]
        self.area = None
        self.mask = None
        self.history = []
        self.before_drag = None
        self.subtract_drag = False
        self.image_size = (1, 1)
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        layout.addLayout(tools)
        self.shape = QComboBox()
        self.shape.addItems(['사각형', '자유선', '마법봉'])
        tools.addWidget(self.shape)
        self.tolerance = QSpinBox()
        self.tolerance.setRange(0, 255)
        self.tolerance.setValue(32)
        self.tolerance.setPrefix('허용 범위 ')
        self.tolerance.hide()
        tools.addWidget(self.tolerance)
        self.delete_button = QPushButton('선택 삭제')
        self.cut_button = QPushButton('잘라내기')
        for button in (self.delete_button, self.cut_button):
            button.setEnabled(False)
            tools.addWidget(button)
        self.delete_button.clicked.connect(lambda: self.remove_selection(False))
        self.cut_button.clicked.connect(lambda: self.remove_selection(True))
        self.move_button = QPushButton('이동·크기 조절 시작')
        self.move_button.setEnabled(False)
        tools.addWidget(self.move_button)
        tools.addWidget(QLabel('배율 %'))
        self.scale = QSpinBox()
        self.scale.setRange(10, 200)
        self.scale.setValue(100)
        self.scale.setEnabled(False)
        tools.addWidget(self.scale)
        tools.addStretch()
        self.guide = QLabel('드래그로 옮기거나 확대할 부분을 선택하세요.')
        layout.addWidget(self.guide)
        self.canvas = MoveCanvas(self)
        layout.addWidget(self.canvas, 1)
        self.apply_button = QPushButton('적용')
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply)
        tools.addWidget(self.apply_button)
        self.timer = QTimer(self, singleShot=True, interval=25)
        self.timer.timeout.connect(self.refresh)
        self.shape.currentIndexChanged.connect(self.set_shape)
        self.canvas.selectionChanged.connect(self.finish_selection)
        self.move_button.clicked.connect(self.toggle_move)
        self.scale.valueChanged.connect(self.refresh)

    def update_buttons(self, rect):
        for button in (self.move_button, self.cut_button, self.delete_button):
            button.setEnabled(rect is not None)

    def pick(self, point, modifiers):
        seed = tuple(min(size - 1, int(v * size)) for size, v in zip(self.image.size, point))
        mask = wand_mask(self.image, seed, self.tolerance.value())
        if modifiers & Qt.KeyboardModifier.AltModifier:
            if self.mask is None:
                return
            mask = ImageChops.subtract(self.mask, mask)
        elif self.mask is not None and modifiers & Qt.KeyboardModifier.ShiftModifier:
            mask = ImageChops.lighter(self.mask, mask)
        self.history.append(self.selection_state())
        self.show_mask(mask)

    def selection_state(self):
        return (self.canvas.selection, self.canvas.outline[:], self.mask)

    def selection_mask(self, rect, outline, mask):
        if mask is not None:
            return mask
        from PIL import Image
        result = Image.new('L', self.image.size)
        if rect is not None:
            box, _, patch = selection_patch(self.image, dict(rect=rect, outline=outline))
            result.paste(patch, box)
        return result

    def finish_selection(self, rect):
        if self.before_drag is not None:
            previous = self.before_drag
            self.before_drag = None
            self.history.append(previous)
            self.mask = None
            if self.subtract_drag:
                current = self.selection_mask(rect, self.canvas.outline, None)
                self.show_mask(ImageChops.subtract(self.selection_mask(*previous), current))
                return
            self.canvas.show_selection = True
            self.canvas.set_image(self.image)
        self.update_buttons(rect)

    def undo_selection(self):
        if self.moving:
            self.toggle_move()
            return True
        if not self.history:
            return False
        rect, outline, mask = self.history.pop()
        self.canvas.selection = rect
        self.canvas.outline = outline
        if mask is not None:
            self.show_mask(mask)
        else:
            self.mask = None
            self.canvas.show_selection = True
            self.canvas.set_image(self.image)
            self.update_buttons(rect)
        return True

    def nudge(self, dx, dy):
        self.offset = [max(-1., min(1., offset + step / size))
                       for offset, step, size in zip(self.offset, (dx, dy), self.image_size)]
        self.refresh()

    def show_mask(self, mask):
        self.canvas.outline.clear()
        self.mask = mask
        box = mask.getbbox()
        self.canvas.selection = [v / self.image.size[i % 2] for i, v in enumerate(box)] if box else None
        self.canvas.show_selection = False
        preview = self.image.copy()
        edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(3)))
        preview.paste((255, 179, 71, 255), (0, 0, *preview.size), edge)
        self.canvas.set_image(preview)
        self.update_buttons(self.canvas.selection)

    def selected_area(self):
        rect = self.canvas.selection[:]
        data = dict(rect=rect, outline=self.canvas.outline[:], offset=[0., 0.], scale=100)
        if self.mask is not None:
            data['mask'] = encode_mask(self.mask.crop(self.mask.getbbox()))
        return data

    def set_base(self, image, image_size=None):
        self.timer.stop()
        self.history.clear()
        self.before_drag = None
        self.image_size = image_size or (image.size if image is not None else (1, 1))
        self.image = image.copy() if image is not None else None
        if self.image is not None:
            self.image.thumbnail((1200, 1200))
        self.moving = False
        self.canvas.drag_start = None
        self.canvas.tracing = False
        self.canvas.start = None
        self.canvas.action = None
        self.shape.setEnabled(True)
        self.scale.setEnabled(False)
        self.move_button.setText('이동·크기 조절 시작')
        self.set_shape(self.shape.currentIndex())
        self.refresh()

    def apply(self):
        change = self.adjustment()
        if change is not None:
            self.commit(change, False)

    def remove_selection(self, cut):
        if self.canvas.selection is not None:
            self.commit(dict(self.selected_area(), remove=True), cut)

    def set_shape(self, index):
        self.mask = None
        self.canvas.show_selection = index != 2
        self.tolerance.setVisible(index == 2)
        self.canvas.set_image(self.image)
        self.canvas.freehand = index == 1
        self.guide.setText('클릭: 선택 · Shift+클릭: 추가 · Alt+클릭: 빼기' if index == 2 else '드래그: 선택 · Alt+드래그: 빼기 · Ctrl+Z: 되돌리기')
        self.canvas.clear_selection()

    def toggle_move(self):
        if self.moving:
            self.moving = False
            rect, outline, mask = self.move_selection
            self.canvas.selection = rect
            self.canvas.outline = outline
            self.mask = mask
            if mask is not None:
                self.show_mask(mask)
            self.update_buttons(rect)
            self.shape.setEnabled(True)
            self.scale.setEnabled(False)
            self.move_button.setText('이동·크기 조절 시작')
            self.guide.setText('드래그로 옮기거나 확대할 부분을 선택하세요.')
        else:
            self.move_selection = self.selection_state()
            self.area = self.selected_area()
            self.cut_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.moving = True
            self.offset = [0., 0.]
            self.canvas.selection = None
            self.canvas.outline.clear()
            self.shape.setEnabled(False)
            self.scale.setValue(100)
            self.scale.setEnabled(True)
            self.move_button.setText('다시 선택')
            self.canvas.setFocus()
            self.guide.setText('그림 위에서 드래그해 옮기세요. 배율은 가운데를 기준으로 조절됩니다. 빈 자리는 흰색으로 채웁니다.')
        self.refresh()

    def adjustment(self):
        if not self.moving or (self.offset == [0., 0.] and self.scale.value() == 100):
            return None
        return dict(self.area, offset=self.offset[:], scale=self.scale.value())

    def refresh(self):
        change = self.adjustment()
        self.apply_button.setEnabled(change is not None)
        if not self.moving and self.mask is not None:
            self.show_mask(self.mask)
        else:
            self.canvas.set_image(render_moves(self.image, [change]) if change else self.image)
