from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QSpinBox, QVBoxLayout)

from area_moves import render_moves
from cut_editor import CutSourceCanvas


class MoveCanvas(CutSourceCanvas):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.drag_start = None
        self.redraw_on_drag = True

    def mousePressEvent(self, event):
        if self.editor.moving and event.button() == Qt.MouseButton.LeftButton:
            if self.begin_pan(event):
                return
            self.drag_start = event.position()
            self.initial_offset = self.editor.offset[:]
            return
        super().mousePressEvent(event)

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


class AreaMoveEditor(QDialog):
    def __init__(self, image, parent):
        super().__init__(parent)
        self.setWindowTitle('영역 이동·크기 조절')
        self.resize(1050, 760)
        self.image = image.copy()
        self.image.thumbnail((1200, 1200))
        self.moving = False
        self.offset = [0., 0.]
        self.area = None
        layout = QVBoxLayout(self)
        tools = QHBoxLayout()
        layout.addLayout(tools)
        self.shape = QComboBox()
        self.shape.addItems(['사각형', '자유선'])
        tools.addWidget(self.shape)
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
        self.canvas.set_image(self.image)
        layout.addWidget(self.canvas, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText('적용')
        self.apply_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.timer = QTimer(self, singleShot=True, interval=25)
        self.timer.timeout.connect(self.refresh)
        self.shape.currentIndexChanged.connect(self.set_shape)
        self.canvas.selectionChanged.connect(lambda rect: self.move_button.setEnabled(rect is not None))
        self.move_button.clicked.connect(self.toggle_move)
        self.scale.valueChanged.connect(self.refresh)

    def set_shape(self, index):
        self.canvas.freehand = index == 1
        self.canvas.clear_selection()

    def toggle_move(self):
        if self.moving:
            self.moving = False
            self.canvas.clear_selection()
            self.canvas.set_image(self.image)
            self.shape.setEnabled(True)
            self.scale.setEnabled(False)
            self.move_button.setText('이동·크기 조절 시작')
            self.guide.setText('드래그로 옮기거나 확대할 부분을 선택하세요.')
        else:
            self.area = (self.canvas.selection[:], self.canvas.outline[:])
            self.moving = True
            self.offset = [0., 0.]
            self.canvas.selection = None
            self.canvas.outline.clear()
            self.shape.setEnabled(False)
            self.scale.setValue(100)
            self.scale.setEnabled(True)
            self.move_button.setText('다시 선택')
            self.guide.setText('그림 위에서 드래그해 옮기세요. 배율은 가운데를 기준으로 조절됩니다. 빈 자리는 흰색으로 채웁니다.')
        self.refresh()

    def adjustment(self):
        if not self.moving or (self.offset == [0., 0.] and self.scale.value() == 100):
            return None
        rect, outline = self.area
        return dict(rect=rect, outline=outline, offset=self.offset[:], scale=self.scale.value())

    def refresh(self):
        change = self.adjustment()
        self.apply_button.setEnabled(change is not None)
        self.canvas.set_image(render_moves(self.image, [change]) if change else self.image)
