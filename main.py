import sys, json, uuid, copy, time
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QRect, QRectF, QPointF, Signal, QObject, QRunnable, QThreadPool, QTimer, QMimeData, QItemSelectionModel, QSettings
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QAction, QKeySequence, QFontDatabase, QFont, QShortcut, QDrag, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QFileDialog,
    QMessageBox, QSlider, QComboBox, QProgressBar, QScrollArea, QStyledItemDelegate, QLayout, QInputDialog, QCheckBox, QLineEdit, QMenu, QDockWidget, QToolButton, QButtonGroup, QStyle, QStyleOptionSlider)
from exporting import prepare_output
from imaging import EXTENSIONS, read_pixels, render_regions, render_entry, render_clones, ClonePreview, export_image, export_pair
from composition import pixel_asset,render_composition,validate_composition

def to_qimage(image):
    rgba = image if image.mode=='RGBA' else image.convert('RGBA')
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()

def tool_icon(index):
    pixmap=QPixmap(64,64);pixmap.setDevicePixelRatio(2);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor('#205a91'),2));painter.setBrush(Qt.BrushStyle.NoBrush)
    if index==0:
        painter.setPen(QPen(QColor('#205a91'),2,Qt.PenStyle.DashLine));painter.drawRect(5,6,22,20)
    elif index==1:
        painter.setPen(QPen(QColor('#205a91'),5,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap));painter.drawLine(14,17,25,6)
        painter.setPen(QPen(QColor('#205a91'),2));painter.setBrush(QColor('#205a91'));painter.drawEllipse(7,16,9,9)
        painter.setPen(Qt.PenStyle.NoPen)
        for x,y in [(4,25),(10,27),(3,19)]:painter.drawRect(x,y,4,4)
    else:
        painter.setBrush(QColor('#205a91'));painter.drawEllipse(11,3,10,10);painter.drawRect(13,11,6,8)
        painter.drawRoundedRect(QRectF(6,18,20,7),2,2);painter.drawRect(4,27,24,3)
    painter.end();return QIcon(pixmap)

class StrengthSlider(QSlider):
    def __init__(self,parent=None):
        super().__init__(Qt.Orientation.Horizontal,parent)
        self.wheel_remainder=0
        self.track_drag=False
        self.setSingleStep(1);self.setPageStep(1)
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            option=QStyleOptionSlider();self.initStyleOption(option)
            handle=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
            if not handle.contains(event.position().toPoint()):
                self.track_drag=True
                groove=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
                start=groove.x();span=max(1,groove.width()-handle.width())
                position=round(event.position().x()-start-handle.width()/2)
                self.setSliderDown(True)
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(),self.maximum(),position,span,option.upsideDown))
                event.accept();return
        super().mousePressEvent(event)
    def mouseMoveEvent(self,event):
        if self.track_drag:
            option=QStyleOptionSlider();self.initStyleOption(option)
            handle=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderHandle,self)
            groove=self.style().subControlRect(QStyle.ComplexControl.CC_Slider,option,QStyle.SubControl.SC_SliderGroove,self)
            position=round(event.position().x()-groove.x()-handle.width()/2)
            self.setValue(QStyle.sliderValueFromPosition(self.minimum(),self.maximum(),position,max(1,groove.width()-handle.width()),option.upsideDown))
            event.accept();return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.track_drag and event.button()==Qt.MouseButton.LeftButton:
            self.track_drag=False;self.setSliderDown(False);event.accept();return
        super().mouseReleaseEvent(event)
    def wheelEvent(self,event):
        self.wheel_remainder+=event.angleDelta().y()
        steps=int(self.wheel_remainder/120)
        self.wheel_remainder-=steps*120
        if steps:self.setValue(self.value()+steps)
        event.accept()

class ToolPicker(QWidget):
    currentIndexChanged=Signal(int)
    activated=Signal()
    def __init__(self,parent=None):
        super().__init__(parent);self.index=0;self.buttons=[];self.group=QButtonGroup(self);self.group.setExclusive(True)
        layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0);layout.setSpacing(5)
        for index,label in enumerate(['박스 모자이크','브러시 모자이크','복제 도장 (Alt+클릭으로 기준점)']):
            button=QToolButton();button.setIcon(tool_icon(index));button.setIconSize(QSize(28,28));button.setCheckable(True)
            button.setToolTip(label);button.setAccessibleName(label);button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(42,40);self.group.addButton(button,index);layout.addWidget(button);self.buttons.append(button)
        self.buttons[0].setChecked(True)
        self.setStyleSheet('QToolButton {border:1px solid #aab8c8;border-radius:5px;background:#edf2f7;} QToolButton:hover {background:#d9eaff;} QToolButton:checked {border:2px solid #287fce;background:#bbddff;}')
        self.group.idClicked.connect(self.choose)
    def choose(self,index):
        self.setCurrentIndex(index);self.activated.emit()
    def currentIndex(self):return self.index
    def setCurrentIndex(self,index):
        if not 0<=index<len(self.buttons):return
        self.buttons[index].setChecked(True)
        if self.index!=index:self.index=index;self.currentIndexChanged.emit(index)

class Signals(QObject):
    done = Signal(object)

class Job(QRunnable):
    def __init__(self, fn, callback):
        super().__init__(); self.fn = fn; self.signals = Signals(); self.signals.done.connect(callback)
    def run(self):
        try: result = (True, self.fn())
        except Exception as exc: result = (False, str(exc))
        self.signals.done.emit(result)

HISTORY_LIMIT = 1000

MOSAIC_ROLE = int(Qt.ItemDataRole.UserRole) + 1
MAIN_ROLE = int(Qt.ItemDataRole.UserRole) + 2

class ThumbnailDelegate(QStyledItemDelegate):
    def sizeHint(self,option,index):
        return QSize(164,150)
    def paint(self,painter,option,index):
        super().paint(painter,option,index)
        if not index.data(MOSAIC_ROLE) and not index.data(MAIN_ROLE):return
        painter.save()
        font=painter.font(); font.setPixelSize(11); font.setBold(True); painter.setFont(font)
        badges=[]
        if index.data(MOSAIC_ROLE):badges.append(('모자이크','#137c59'))
        if index.data(MAIN_ROLE):badges.append(('메인','#7446b8'))
        for offset,(label,color) in enumerate(badges):
            badge=QRectF(option.rect.right()-68,option.rect.top()+5+offset*26,64,23)
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(color)); painter.drawRoundedRect(badge,5,5)
            painter.setPen(QColor('white')); painter.drawText(badge,Qt.AlignmentFlag.AlignCenter,label)
        painter.restore()

class ImageList(QListWidget):
    dropped = Signal(list,int)
    reordered = Signal()
    reordering = Signal()
    def __init__(self):
        super().__init__()
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(140, 110)); self.setGridSize(QSize(164, 150))
        self.setUniformItemSizes(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(True); self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(5); self.setAcceptDrops(True)
        # Static icon movement disables viewport drops in Qt. Enable the actual
        # surface explicitly, otherwise explorer drops bubble up to Window.
        self.viewport().setAcceptDrops(True)
        self.setSelectionRectVisible(False)
        self.empty_press=False
        self.hover_row=-1;self.selection_anchor=None;self.collapse_on_release=None
        self.press_position=None; self.drag_ids=[]; self.dragging=False; self.drop_target=None
        self.setMouseTracking(True)
    def cell_rect(self,row):
        rect=self.visualItemRect(self.item(row))
        return QRect(round(rect.x()+rect.width()/2-self.gridSize().width()/2),rect.top(),self.gridSize().width(),self.gridSize().height())
    def row_at(self,pos):
        if not self.viewport().rect().contains(pos):return -1
        for row in range(self.count()):
            if self.cell_rect(row).contains(pos):return row
        return -1
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:
            row=self.row_at(event.position().toPoint())
            if row>=0 and not self.item(row).isSelected():
                self.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.selection_anchor=self.item(row).data(Qt.ItemDataRole.UserRole)
            self.setFocus(Qt.FocusReason.MouseFocusReason);event.accept();return
        if event.button()!=Qt.MouseButton.LeftButton:
            super().mousePressEvent(event);return
        pos=event.position().toPoint();row=self.row_at(pos)
        self.press_position=None;self.dragging=False;self.drop_target=None;self.collapse_on_release=None
        self.empty_press=row<0
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if row<0:event.accept();return
        item=self.item(row);mods=event.modifiers()
        control=bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift=bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            anchor=next((i for i in range(self.count()) if self.item(i).data(Qt.ItemDataRole.UserRole)==self.selection_anchor),max(0,self.currentRow()))
            if not control:self.clearSelection()
            for i in range(min(anchor,row),max(anchor,row)+1):self.item(i).setSelected(True)
        elif control:
            item.setSelected(not item.isSelected());self.selection_anchor=item.data(Qt.ItemDataRole.UserRole)
        elif item.isSelected():
            self.collapse_on_release=item.data(Qt.ItemDataRole.UserRole)
            self.selection_anchor=item.data(Qt.ItemDataRole.UserRole)
        else:
            self.clearSelection();item.setSelected(True);self.selection_anchor=item.data(Qt.ItemDataRole.UserRole)
        self.setCurrentItem(item,QItemSelectionModel.SelectionFlag.NoUpdate)
        if item.isSelected():
            self.press_position=pos
            self.drag_ids=[self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count()) if self.item(i).isSelected()]
        self.itemPressed.emit(item);self.viewport().update();event.accept()
    def target_at(self,pos):
        if not self.count():return 0
        # Pick the visual row by Y first. X must never pull a row-end drop
        # toward the first item of the next row.
        bands={}
        for row in range(self.count()):
            rect=self.visualItemRect(self.item(row))
            bands.setdefault(rect.top(),[]).append((row,rect))
        band=min(bands.values(),key=lambda items:abs(items[0][1].center().y()-pos.y()))
        band.sort(key=lambda pair:pair[1].center().x())
        if pos.y()>max(rect.bottom() for _,rect in band)+self.gridSize().height()/2:
            row,rect=band[-1];target=row+1;marker=rect.right()+3
        else:
            for row,rect in band:
                if pos.x()<rect.center().x():
                    target=row;marker=rect.left()-3;break
            else:
                row,rect=band[-1];target=row+1;marker=rect.right()+3
        self.drop_marker=(max(3,min(self.viewport().width()-3,marker)),rect.top(),rect.bottom())
        return target
    def mouseMoveEvent(self,event):
        hover=self.row_at(event.position().toPoint())
        if hover!=self.hover_row:self.hover_row=hover;self.viewport().update()
        if self.press_position is not None:
            pos=event.position().toPoint()
            if not self.dragging and (pos-self.press_position).manhattanLength()>=QApplication.startDragDistance():
                self.dragging=True; self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            if self.dragging:
                bar=self.verticalScrollBar()
                if pos.y()<30:bar.setValue(bar.value()-24)
                elif pos.y()>self.viewport().height()-30:bar.setValue(bar.value()+24)
                self.drop_target=self.target_at(pos); self.viewport().update()
            event.accept(); return
        event.accept()
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.RightButton:event.accept();return
        if event.button()!=Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event);return
        if self.dragging:
            target=self.target_at(event.position().toPoint());ids=self.drag_ids[:]
            self.press_position=None;self.dragging=False;self.drop_target=None;self.collapse_on_release=None
            self.viewport().unsetCursor();self.move_ids(ids,target)
            self.hover_row=self.row_at(event.position().toPoint())
        else:
            row=self.row_at(event.position().toPoint())
            if self.collapse_on_release is not None and row>=0:
                item=self.item(row)
                if item.data(Qt.ItemDataRole.UserRole)==self.collapse_on_release:
                    self.clearSelection();item.setSelected(True)
            if row>=0 and not self.empty_press:self.itemClicked.emit(self.item(row))
        self.press_position=None;self.empty_press=False;self.collapse_on_release=None
        self.setState(QAbstractItemView.State.NoState);self.viewport().update();event.accept()
    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Up,Qt.Key.Key_Down) and event.modifiers()==Qt.KeyboardModifier.NoModifier:
            action=QAbstractItemView.CursorAction.MoveUp if event.key()==Qt.Key.Key_Up else QAbstractItemView.CursorAction.MoveDown
            index=self.moveCursor(action,event.modifiers())
            if index.isValid():
                self.setCurrentRow(index.row(),QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.selection_anchor=self.item(index.row()).data(Qt.ItemDataRole.UserRole)
                self.scrollTo(index)
            event.accept();return
        super().keyPressEvent(event)
    def leaveEvent(self,event):
        self.hover_row=-1;self.viewport().update();super().leaveEvent(event)
    def paintEvent(self,event):
        super().paintEvent(event)
        painter=QPainter(self.viewport())
        for row in range(self.count()):
            rect=self.cell_rect(row).adjusted(2,2,-2,-2)
            if not rect.intersects(self.viewport().rect()):continue
            selected=self.item(row).isSelected();hover=row==self.hover_row
            if selected or hover:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(QColor('#62bcff' if selected else '#a3d5ff'),3 if selected else 2))
                painter.drawRoundedRect(rect,5,5)
        painter.end()
        if self.drop_target is None or not self.count():return
        painter=QPainter(self.viewport()); painter.setPen(QPen(QColor('#ffab40'),4))
        if hasattr(self,'drop_marker'):
            x,top,bottom=self.drop_marker
            painter.drawLine(x,top,x,bottom)
            painter.drawLine(x-5,top,x+5,top)
            painter.drawLine(x-5,bottom,x+5,bottom)
    MIME = 'application/x-photo-item-ids'
    def startDrag(self, supported_actions):
        ids=[self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count()) if self.item(row).isSelected()]
        if not ids:return
        mime=QMimeData(); mime.setData(self.MIME,json.dumps(ids).encode('utf-8'))
        drag=QDrag(self); drag.setMimeData(mime)
        item=self.currentItem()
        if item and not item.icon().isNull():drag.setPixmap(item.icon().pixmap(100,80))
        # Own the entire move: Qt's built-in source cleanup must not remove rows again.
        drag.exec(Qt.DropAction.MoveAction)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self.drop_target=self.target_at(event.position().toPoint());self.viewport().update()
            event.setDropAction(Qt.DropAction.CopyAction);event.accept()
        elif event.mimeData().hasFormat(self.MIME):event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(self.MIME):
            pos=event.position().toPoint();bar=self.verticalScrollBar()
            if pos.y()<30:bar.setValue(bar.value()-24)
            elif pos.y()>self.viewport().height()-30:bar.setValue(bar.value()+24)
            self.drop_target=self.target_at(pos);self.viewport().update()
            if event.mimeData().hasUrls():event.setDropAction(Qt.DropAction.CopyAction);event.accept()
            else:event.acceptProposedAction()
        else:event.ignore()
    def dragLeaveEvent(self,event):
        self.drop_target=None;self.viewport().update();event.accept()
    def move_ids(self, ids, target):
        rows=[row for row in range(self.count()) if self.item(row).data(Qt.ItemDataRole.UserRole) in ids]
        if not rows:return
        target=max(0,min(self.count(),target))
        remaining=[self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count()) if row not in rows]
        moving=[self.item(row).data(Qt.ItemDataRole.UserRole) for row in rows]
        target-=sum(row<target for row in rows)
        if remaining[:target]+moving+remaining[target:]==[self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count())]:return
        self.reordering.emit(); self.blockSignals(True)
        items=[self.takeItem(row) for row in reversed(rows)][::-1]
        for offset,item in enumerate(items):self.insertItem(target+offset,item)
        self.clearSelection()
        self.setCurrentItem(items[0])
        for item in items:item.setSelected(True)
        self.blockSignals(False); self.doItemsLayout()
        self.currentItemChanged.emit(items[0],None); self.reordered.emit()
    def dropEvent(self, event):
        try:
            target=self.target_at(event.position().toPoint())
            if event.mimeData().hasUrls():
                files=[url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
                self.dropped.emit(files,target);event.setDropAction(Qt.DropAction.CopyAction);event.accept()
            elif event.mimeData().hasFormat(self.MIME):
                try:ids=json.loads(bytes(event.mimeData().data(self.MIME)).decode('utf-8'))
                except (ValueError,UnicodeDecodeError):event.ignore();return
                self.move_ids(ids,target);event.setDropAction(Qt.DropAction.MoveAction);event.accept()
            else:event.ignore()
        finally:
            self.drop_target=None;self.viewport().update()

class Canvas(QWidget):
    selected = Signal(object)
    zoomChanged = Signal(float)
    def __init__(self):
        super().__init__(); self.setMinimumSize(320, 300)
        self.pixmap = None; self.regions = []; self.active = -1; self.start = None; self.end = None
        self.tool='box'; self.brush_radius=.025; self.stroke=[]; self.drawing_brush=False
        self.clone_source=None;self.drawing_clone=False;self.clone_softness=.5;self.hover=None;self.setMouseTracking(True)
        self.zoom = 1.0;self.pan=QPointF();self.pan_start=None; self.target = QRectF()
    def update_target(self):
        if not self.pixmap:return
        size=self.pixmap.size();scale=min(self.width()/size.width(),self.height()/size.height())*self.zoom
        width,height=size.width()*scale,size.height()*scale
        self.target=QRectF((self.width()-width)/2+self.pan.x(),(self.height()-height)/2+self.pan.y(),width,height)
    def reset_view(self):
        self.zoom=1.;self.pan=QPointF();self.pan_start=None
        self.update_target();self.zoomChanged.emit(self.zoom);self.update()
    def wheelEvent(self,event):
        if not self.pixmap:event.ignore();return
        if self.start is not None or self.drawing_brush or self.drawing_clone:event.accept();return
        delta=event.angleDelta().y()/120
        if not delta:delta=event.pixelDelta().y()/120
        if not delta:event.accept();return
        self.update_target();point=event.position()
        u=(point.x()-self.target.x())/self.target.width();v=(point.y()-self.target.y())/self.target.height()
        self.zoom=max(.25,min(16.,self.zoom*1.2**delta));self.update_target()
        self.pan+=QPointF(point.x()-(self.target.x()+u*self.target.width()),point.y()-(self.target.y()+v*self.target.height()))
        self.update_target();self.hover=point;self.zoomChanged.emit(self.zoom);self.update();event.accept()
    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.MiddleButton:self.reset_view();event.accept();return
        super().mouseDoubleClickEvent(event)
    def normalized(self, point):
        return (max(0., min(1., (point.x()-self.target.x())/max(1,self.target.width()))),
                max(0., min(1., (point.y()-self.target.y())/max(1,self.target.height()))))
    def paintEvent(self, event):
        p = QPainter(self); p.fillRect(self.rect(), QColor('#14171d'))
        if not self.pixmap:
            p.setPen(QColor('#a4aec0')); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '그림을 드래그해서 추가하세요'); return
        self.update_target();w,h=self.target.width(),self.target.height()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.tool=='clone':
            p.setPen(QPen(QColor('#ffcf66'),1))
            if self.clone_source is not None:
                x=self.target.x()+self.clone_source[0]*w;y=self.target.y()+self.clone_source[1]*h
                p.drawLine(int(x)-6,int(y),int(x)+6,int(y));p.drawLine(int(x),int(y)-6,int(x),int(y)+6)
            if self.hover is not None and self.target.contains(self.hover):
                radius=self.brush_radius*w;p.drawEllipse(self.hover,radius,radius)
        if self.start is not None and self.end is not None:
            p.setPen(QPen(QColor('#ffffff'),2,Qt.PenStyle.DashLine)); p.drawRect(QRectF(self.start,self.end).normalized())
    def mousePressEvent(self,event):
        if self.pixmap and (event.button()==Qt.MouseButton.MiddleButton or (event.button()==Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier)):
            self.pan_start=event.position();self.setCursor(Qt.CursorShape.ClosedHandCursor);event.accept();return
        if self.pixmap and self.tool=='clone' and event.button()==Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                self.clone_source=self.normalized(event.position());self.selected.emit(('clone_source',self.clone_source));self.update();return
            if self.clone_source is None:self.selected.emit(('clone_missing',None));return
            self.drawing_clone=True;self.stroke=[self.normalized(event.position())]
            self.selected.emit(('clone_start',{'source':list(self.clone_source),'points':self.stroke.copy(),'radius':self.brush_radius,'softness':self.clone_softness}));return
        if self.pixmap and event.button()==Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            if self.tool=='brush':
                self.drawing_brush=True; self.stroke=[self.normalized(event.position())]
                self.selected.emit(('brush_start',{'points':self.stroke.copy(),'radius':self.brush_radius}))
            else:
                self.start=event.position(); self.end=self.start
    def mouseMoveEvent(self,event):
        self.hover=event.position();self.update()
        if self.pan_start is not None:
            self.pan+=event.position()-self.pan_start;self.pan_start=event.position();self.update_target();event.accept();return
        if self.drawing_clone:
            self.stroke.append(self.normalized(event.position()));self.selected.emit(('clone_move',self.stroke.copy()));return
        if self.drawing_brush:
            self.stroke.append(self.normalized(event.position()))
            self.selected.emit(('brush_move',self.stroke.copy()))
            return
        if self.start is not None: self.end=event.position(); self.update()
    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.MiddleButton or (self.pan_start is not None and event.button()==Qt.MouseButton.LeftButton):
            self.pan_start=None;self.unsetCursor();event.accept();return
        if self.drawing_clone:
            self.stroke.append(self.normalized(event.position()));self.drawing_clone=False;self.selected.emit(('clone_end',self.stroke.copy()));return
        if self.drawing_brush:
            self.stroke.append(self.normalized(event.position()))
            self.selected.emit(('brush_move',self.stroke.copy()))
            self.drawing_brush=False; return
        if self.start is None: return
        a,b=self.normalized(self.start); c,d=self.normalized(event.position())
        if abs(event.position().x()-self.start.x())>5 and abs(event.position().y()-self.start.y())>5:
            self.selected.emit(('add',[min(a,c),min(b,d),max(a,c),max(b,d)]))
        else:
            index=next((i for i in reversed(range(len(self.regions))) if self.regions[i]['rect'][0]<=a<=self.regions[i]['rect'][2] and self.regions[i]['rect'][1]<=b<=self.regions[i]['rect'][3]),-1)
            self.selected.emit(('select',index))
        self.start=None; self.end=None; self.update()

class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle('Photo · 그림 정리와 모자이크 · 순서 드래그 수정 v0.2.43'); self.resize(1400,900)
        self.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'photo.png')))
        self.settings=QSettings('PhotoOrganizer','Photo')
        legacy_size=self.settings.value('tools/size',50,type=int)
        self.tool_sizes={name:max(5,min(200,self.settings.value('tools/sizes/'+name,legacy_size,type=int))) for name in ['box','brush','clone']}
        self.export_folder=str(self.settings.value('export/folder',''))
        try:self.recent_projects=json.loads(str(self.settings.value('projects/recent','[]')))
        except (ValueError,TypeError):self.recent_projects=[]
        if not isinstance(self.recent_projects,list):self.recent_projects=[]
        self.recent_projects=[path for path in self.recent_projects if isinstance(path,str)]
        self.entries={}; self.cache=OrderedDict(); self.pending=set(); self.history=[]; self.history_labels=[]; self.redo_stack=[]; self.snapshot_cache={}; self.strength_drag_recorded=False; self.dirty=False; self.project=None
        self.clone_cache_key=None;self.clone_cache_image=None;self.clone_live=None;self.clone_live_entry=None
        self.cut_clipboard=None;self.composition_cache_key=None;self.composition_cache_image=None
        self.clone_timer=QTimer(self);self.clone_timer.setSingleShot(True);self.clone_timer.timeout.connect(self.flush_clone_preview)
        self.thumb_cache=OrderedDict();self.thumb_waiters={};self.thumb_cache_bytes=0
        self.pool=QThreadPool(self); self.pool.setMaxThreadCount(4)
        self.preview_pool=QThreadPool(self); self.preview_pool.setMaxThreadCount(2)
        self.export_pool=QThreadPool(self); self.export_pool.setMaxThreadCount(1)
        self.jobs=set(); self.errors=[]; self.busy=False
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root)
        top=QHBoxLayout(); layout.addLayout(top)
        for label,fn in [('파일 추가',self.add_dialog),('폴더 추가',self.folder_dialog),('작업 열기',self.load_project),('작업 저장',self.save_project),('다른 이름으로 저장',self.save_project_as),('실행 취소',self.undo),('다시 실행',self.redo),('목록에서 제외',self.remove_selected)]:
            button=QPushButton(label); button.clicked.connect(fn); top.addWidget(button)
            icons={'파일 추가':QStyle.StandardPixmap.SP_FileIcon,'폴더 추가':QStyle.StandardPixmap.SP_DirIcon,
                   '작업 열기':QStyle.StandardPixmap.SP_DialogOpenButton,'작업 저장':QStyle.StandardPixmap.SP_DialogSaveButton,
                   '다른 이름으로 저장':QStyle.StandardPixmap.SP_DialogSaveButton,'목록에서 제외':QStyle.StandardPixmap.SP_TrashIcon}
            if label in icons:button.setIcon(self.style().standardIcon(icons[label]));button.setIconSize(QSize(16,16))
            if label=='실행 취소':self.undo_button=button
            elif label=='다시 실행':self.redo_button=button
        self.history_dock=QDockWidget('저장한 작업',self);self.history_dock.setObjectName('photoHistoryDock')
        self.history_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea|Qt.DockWidgetArea.RightDockWidgetArea)
        history_body=QWidget();history_layout=QVBoxLayout(history_body)
        self.history_summary=QLabel('저장한 작업 0개');history_layout.addWidget(self.history_summary)
        self.history_list=QListWidget();self.history_list.setMinimumWidth(170);history_layout.addWidget(self.history_list)
        self.history_list.itemClicked.connect(self.open_recent_project)
        add_project_button=QPushButton('작업 파일 추가');add_project_button.clicked.connect(self.add_project_files);history_layout.addWidget(add_project_button)
        find_projects_button=QPushButton('폴더에서 작업 찾기');find_projects_button.clicked.connect(self.find_projects);history_layout.addWidget(find_projects_button)
        self.history_dock.setWidget(history_body);self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.history_dock)
        self.resizeDocks([self.history_dock],[210],Qt.Orientation.Horizontal)
        history_toggle=QPushButton('저장한 작업');history_toggle.setCheckable(True);history_toggle.setChecked(True)
        history_toggle.toggled.connect(self.history_dock.setVisible);self.history_dock.visibilityChanged.connect(history_toggle.setChecked)
        top.addWidget(history_toggle);self.history_toggle=history_toggle
        top.addStretch()
        export_controls=QHBoxLayout();layout.addLayout(export_controls)
        folder_button=QPushButton('저장 위치 변경');folder_button.clicked.connect(self.choose_export_folder);export_controls.addWidget(folder_button)
        self.export_folder_label=QLabel(self.export_folder or '저장 위치: 최초 내보내기 때 선택');self.export_folder_label.setToolTip(self.export_folder)
        self.export_folder_label.setMaximumWidth(320);export_controls.addWidget(self.export_folder_label)
        export_controls.addStretch();export_controls.addWidget(QLabel('폴더 이름'))
        self.export_name=QLineEdit(str(self.settings.value('export/name','a')));self.export_name.setMaximumWidth(150);export_controls.addWidget(self.export_name)
        self.output_checks={}
        for key,label in [('cen','처리본'),('uncen','원본용'),('main','메인용')]:
            check=QCheckBox(label);check.setChecked(self.settings.value('export/'+key,True,type=bool))
            check.toggled.connect(lambda value,k=key:self.settings.setValue('export/'+k,value))
            self.output_checks[key]=check;export_controls.addWidget(check)
        self.format=QComboBox(); self.format.addItems(['PNG','WEBP','JPEG']); export_controls.addWidget(self.format)
        self.export_button=QPushButton('순서대로 내보내기'); self.export_button.clicked.connect(self.export); export_controls.addWidget(self.export_button)
        self.splitter=QSplitter(Qt.Orientation.Horizontal); splitter=self.splitter
        splitter.setHandleWidth(5); splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet('QSplitter::handle:horizontal {background:#c2cbd6;border:0;} QSplitter::handle:horizontal:hover {background:#2788e8;}')
        layout.addWidget(splitter,1)
        left=QWidget(); ll=QVBoxLayout(left)
        thumbnail_header=QHBoxLayout();ll.addLayout(thumbnail_header)
        thumbnail_header.addWidget(QLabel('드래그로 순서 변경 · Delete로 제외'))
        thumbnail_header.addStretch();self.selection_count=QLabel('선택 0장');thumbnail_header.addWidget(self.selection_count)
        self.list=ImageList(); ll.addWidget(self.list); splitter.addWidget(left)
        self.list.itemSelectionChanged.connect(self.update_selection_count)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.thumbnail_context_menu)
        left.setMinimumWidth(180)
        right=QWidget(); right.setMinimumWidth(460); rl=QVBoxLayout(right)
        rl.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.title=QLabel('그림을 선택하세요'); rl.addWidget(self.title)
        self.main_check=QCheckBox('메인 게시용으로 선택 · 별도 폴더에도 저장')
        self.main_check.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.main_check.setEnabled(False); self.main_check.toggled.connect(self.toggle_main)
        rl.addWidget(self.main_check)
        self.canvas=Canvas();self.canvas.setMinimumHeight(160)
        self.preview_splitter=QSplitter(Qt.Orientation.Vertical);self.preview_splitter.setHandleWidth(5);self.preview_splitter.setChildrenCollapsible(False)
        self.preview_splitter.setStyleSheet('QSplitter::handle:vertical {background:#c2cbd6;border:0;} QSplitter::handle:vertical:hover {background:#2788e8;}')
        self.preview_splitter.addWidget(self.canvas);rl.addWidget(self.preview_splitter,1)
        tools_panel=QWidget();bottom_layout=QVBoxLayout(tools_panel);bottom_layout.setContentsMargins(2,4,2,2)
        tools_scroll=QScrollArea();tools_scroll.setWidgetResizable(True);tools_scroll.setWidget(tools_panel);tools_scroll.setMinimumHeight(80)
        self.preview_splitter.addWidget(tools_scroll)
        view_controls=QHBoxLayout();bottom_layout.addLayout(view_controls)
        fit_button=QPushButton('화면에 맞춤');fit_button.clicked.connect(self.canvas.reset_view);view_controls.addWidget(fit_button)
        self.zoom_label=QLabel('100%');view_controls.addWidget(self.zoom_label)
        self.canvas.zoomChanged.connect(lambda zoom:self.zoom_label.setText(f'{zoom*100:.0f}%'))
        view_controls.addWidget(QLabel('휠: 확대/축소 · Ctrl+드래그 또는 휠버튼 드래그: 이동'));view_controls.addStretch()
        cut_controls=QHBoxLayout();bottom_layout.addLayout(cut_controls)
        for label,fn in [('컷 편집 / 부분 자르기',self.edit_cuts)]:
            button=QPushButton(label);button.clicked.connect(fn);cut_controls.addWidget(button)
        cut_controls.addWidget(QLabel('영역 선택 → 자유 배치 · 원래 해상도로 채우기'));cut_controls.addStretch()
        brush_tools=QHBoxLayout(); bottom_layout.addLayout(brush_tools)
        brush_tools.addWidget(QLabel('도구'))
        self.tool=ToolPicker(); brush_tools.addWidget(self.tool)
        self.tool.currentIndexChanged.connect(self.change_tool)
        self.tool.activated.connect(lambda:self.list.setFocus(Qt.FocusReason.OtherFocusReason))
        brush_tools.addWidget(QLabel('브러시 크기'))
        self.brush_size=QSlider(Qt.Orientation.Horizontal); self.brush_size.setRange(5,200); self.brush_size.setValue(50)
        self.brush_size.valueChanged.connect(self.change_brush_size)
        brush_tools.addWidget(self.brush_size)
        self.brush_value=QLabel('50'); brush_tools.addWidget(self.brush_value)
        self.brush_size.valueChanged.connect(lambda value:self.brush_value.setText(str(value)))
        softness_tools=QHBoxLayout();bottom_layout.addLayout(softness_tools)
        softness_tools.addWidget(QLabel('도장 경계 부드러움'))
        self.clone_softness=QSlider(Qt.Orientation.Horizontal);self.clone_softness.setRange(0,100);self.clone_softness.setValue(50)
        self.clone_softness.valueChanged.connect(lambda value:setattr(self.canvas,'clone_softness',value/100))
        softness_tools.addWidget(self.clone_softness)
        softness_tools.addWidget(QLabel('도장: Alt+클릭으로 기준점 · 드래그로 덮기'))
        tools=QHBoxLayout(); bottom_layout.addLayout(tools)
        tools.addWidget(QLabel('모자이크 강도'))
        self.strength=StrengthSlider(); self.strength.setTracking(True); self.strength.setRange(2,100); self.strength.setValue(20); tools.addWidget(self.strength)
        self.value=QLabel('20'); tools.addWidget(self.value)
        delete_region=QPushButton('선택 영역 삭제'); tools.addWidget(delete_region); delete_region.clicked.connect(self.remove_region)
        self.original=QPushButton('원본 비교'); self.original.setCheckable(True); tools.addWidget(self.original); self.original.toggled.connect(self.render)
        batch_tools=QHBoxLayout(); bottom_layout.addLayout(batch_tools)
        self.batch_strength_button=QPushButton('선택 사진 강도 일괄 변경')
        self.batch_strength_button.clicked.connect(self.batch_strength_dialog); batch_tools.addWidget(self.batch_strength_button)
        reset_button=QPushButton('모자이크 초기화');reset_menu=QMenu(reset_button)
        reset_menu.addAction('현재 그림의 모자이크 모두 제거',lambda:self.clear_mosaics([self.current()['id']] if self.current() else []))
        reset_menu.addAction('선택한 그림들의 모자이크 모두 제거',lambda:self.clear_mosaics([item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]))
        reset_menu.addAction('모든 그림의 모자이크 모두 제거',lambda:self.clear_mosaics(list(self.entries)))
        reset_button.setMenu(reset_menu);batch_tools.addWidget(reset_button)
        batch_tools.addWidget(QLabel('Ctrl/Shift로 여러 장 선택 · Ctrl+A로 전체 선택')); batch_tools.addStretch()
        bottom_layout.addWidget(QLabel('박스: 드래그 / 영역 클릭 · 브러시: 문지르기 · Ctrl+Z: 취소 · ← / →: 이전 / 다음 그림'))
        bottom_layout.addStretch()
        self.preview_splitter.setStretchFactor(0,1);self.preview_splitter.setStretchFactor(1,0);self.preview_splitter.setSizes([560,230])
        saved_vertical=self.settings.value('layout/previewVertical')
        if saved_vertical is not None:self.preview_splitter.restoreState(saved_vertical)
        self.preview_splitter.setHandleWidth(5)
        self.preview_splitter.splitterMoved.connect(lambda pos,index:self.settings.setValue('layout/previewVertical',self.preview_splitter.saveState()))
        self.preview_splitter.handle(1).setCursor(Qt.CursorShape.SizeVerCursor)
        self.preview_splitter.handle(1).setToolTip('위아래로 드래그해서 그림과 아래 도구 영역 높이 조절')
        splitter.addWidget(right); splitter.setSizes([580,820])
        saved_splitter=self.settings.value('layout/splitter')
        if saved_splitter is not None:splitter.restoreState(saved_splitter)
        splitter.setHandleWidth(5)
        splitter.splitterMoved.connect(lambda pos,index:self.settings.setValue('layout/splitter',splitter.saveState()))
        splitter.handle(1).setCursor(Qt.CursorShape.SizeHorCursor)
        splitter.handle(1).setToolTip('좌우로 드래그해서 썸네일과 미리보기 너비 조절')
        self.progress=QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        footer=QHBoxLayout();layout.addLayout(footer)
        self.status=QLabel('원본을 보존하며, 결과 파일에는 메타데이터를 저장하지 않습니다.'); footer.addWidget(self.status,1)
        self.bottom_selection_count=QLabel('선택 0장 / 전체 0장');footer.addWidget(self.bottom_selection_count)
        self.list.dropped.connect(self.add_paths); self.list.currentItemChanged.connect(self.selection_changed)
        self.list.reordering.connect(lambda:self.snapshot('그림 순서 변경')); self.list.reordered.connect(self.order_changed); self.canvas.selected.connect(self.region_event)
        self.strength.valueChanged.connect(self.strength_changed)
        self.strength.valueChanged.connect(lambda value:self.settings.setValue('tools/strength',value))
        self.clone_softness.valueChanged.connect(lambda value:self.settings.setValue('tools/softness',value))
        self.strength.sliderPressed.connect(self.begin_strength_change)
        self.strength.sliderMoved.connect(self.strength.setValue)
        self.strength.sliderReleased.connect(self.begin_strength_change)
        for key,fn in [('Delete',self.remove_selected),('Ctrl+S',self.save_project),('Ctrl+Shift+S',self.save_project_as),('Ctrl+O',self.load_project),('Right',lambda:self.navigate(1)),('Left',lambda:self.navigate(-1))]:
            action=QAction(self); action.setShortcut(QKeySequence(key)); action.triggered.connect(fn); self.addAction(action)
        self.undo_shortcut=QShortcut(QKeySequence.StandardKey.Undo,self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.undo_shortcut.activated.connect(self.undo)
        self.redo_shortcuts=[]
        for key in ['Ctrl+Y','Ctrl+Shift+Z']:
            shortcut=QShortcut(QKeySequence(key),self);shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(self.redo);self.redo_shortcuts.append(shortcut)
        self.tool.setCurrentIndex(max(0,min(2,self.settings.value('tools/selected',0,type=int))))
        self.strength.setValue(self.settings.value('tools/strength',20,type=int))
        self.change_tool(self.tool.currentIndex())
        self.clone_softness.setValue(self.settings.value('tools/softness',50,type=int))
        saved_layout=self.settings.value('layout/windowState')
        if saved_layout is not None:self.restoreState(saved_layout)
        self.refresh_recent_projects()
        self.update_history_controls()
        self.setAcceptDrops(True)
    def change_tool(self,index):
        name=['box','brush','clone'][index]
        self.canvas.tool=name;self.settings.setValue('tools/selected',index)
        value=self.tool_sizes[name]
        self.brush_size.blockSignals(True);self.brush_size.setValue(value);self.brush_size.blockSignals(False)
        self.brush_value.setText(str(value));self.canvas.brush_radius=value/2000;self.canvas.update()
    def change_brush_size(self,value):
        name=self.canvas.tool
        self.tool_sizes[name]=value;self.settings.setValue('tools/sizes/'+name,value)
        self.canvas.brush_radius=value/2000;self.canvas.update()
    def run_job(self,pool,fn,callback,priority=0):
        job=Job(fn,lambda result:self.job_done(job,callback,result)); self.jobs.add(job); pool.start(job,priority)
    def job_done(self,job,callback,result):
        self.jobs.discard(job); callback(result)
    def dragEnterEvent(self,event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self,event):
        self.add_paths([u.toLocalFile() for u in event.mimeData().urls()]); event.acceptProposedAction()
    def ordered(self): return [self.entries[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]
    def current(self):
        item=self.list.currentItem(); return self.entries.get(item.data(Qt.ItemDataRole.UserRole)) if item else None
    def refresh_recent_projects(self):
        self.history_summary.setText(f'저장한 작업 {len(self.recent_projects)}개 · 클릭해서 열기')
        self.history_list.clear()
        for path in self.recent_projects:
            file=Path(path);name=file.name.removesuffix('.photo.json')
            item=QListWidgetItem(name+('  [현재 작업]' if self.project==path else '')+('  [파일 없음]' if not file.is_file() else ''))
            item.setData(Qt.ItemDataRole.UserRole,path);item.setToolTip(path);self.history_list.addItem(item)
            if self.project==path:
                font=item.font();font.setBold(True);item.setFont(font);self.history_list.setCurrentItem(item)
        if not self.recent_projects:
            empty=QListWidgetItem('저장하거나 연 작업이 여기에 표시됩니다.');empty.setFlags(Qt.ItemFlag.NoItemFlags);self.history_list.addItem(empty)
    def remember_project(self,path):
        path=str(Path(path).resolve())
        self.recent_projects=([path]+[old for old in self.recent_projects if old!=path])[:100]
        self.settings.setValue('projects/recent',json.dumps(self.recent_projects,ensure_ascii=False))
        self.refresh_recent_projects()
    def open_recent_project(self,item):
        path=item.data(Qt.ItemDataRole.UserRole)
        if not path or path==self.project:return
        self.open_project(path)
    def add_project_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'저장한 작업 목록에 추가','','Photo project (*.photo.json)')
        for path in reversed(paths):self.remember_project(path)
    def find_projects(self):
        folder=QFileDialog.getExistingDirectory(self,'작업 JSON이 저장된 폴더')
        if not folder:return
        paths=sorted(Path(folder).rglob('*.photo.json'),key=lambda path:path.stat().st_mtime_ns)
        for path in paths:self.remember_project(path)
        self.status.setText(f'저장한 작업 {len(paths)}개를 목록에 추가했습니다.')
    def capture_state(self):
        entry=self.current()
        state=[]
        for image in self.ordered():
            cached=self.snapshot_cache.get(image['id'])
            if cached is None or cached!=image:
                previous=cached or {}
                frozen={key:copy.deepcopy(value) for key,value in image.items() if key not in ('regions','clones')}
                for field in ('regions','clones'):
                    if field not in image:continue
                    old=previous.get(field,[])
                    frozen[field]=[old[index] if index<len(old) and old[index]==value else copy.deepcopy(value) for index,value in enumerate(image[field])]
                cached=frozen;self.snapshot_cache[image['id']]=cached
            state.append(cached)
        return (state,entry['id'] if entry else None,self.canvas.active)
    def update_history_controls(self):
        self.undo_button.setEnabled(bool(self.history));self.redo_button.setEnabled(bool(self.redo_stack))
        self.undo_button.setToolTip('Ctrl+Z');self.redo_button.setToolTip('Ctrl+Y 또는 Ctrl+Shift+Z')
    def snapshot(self,label='작업 변경'):
        self.history.append(self.capture_state())
        self.history=self.history[-HISTORY_LIMIT:];self.history_labels.append(label);self.history_labels=self.history_labels[-HISTORY_LIMIT:]
        self.redo_stack.clear();self.update_history_controls();self.dirty=True
    def undo(self):
        if not self.history:return
        label=self.history_labels.pop() if self.history_labels else '작업 변경'
        self.redo_stack.append((self.capture_state(),label))
        self.restore_state(self.history.pop());self.update_history_controls()
        self.status.setText('실행 취소: '+label)
    def redo(self):
        if not self.redo_stack:return
        state,label=self.redo_stack.pop()
        self.history.append(self.capture_state());self.history=self.history[-HISTORY_LIMIT:]
        self.history_labels.append(label);self.history_labels=self.history_labels[-HISTORY_LIMIT:]
        self.restore_state(state);self.update_history_controls()
        self.status.setText('다시 실행: '+label)
    def restore_state(self,snapshot):
        self.clone_timer.stop();self.clone_live=None;self.clone_live_entry=None
        self.clone_cache_key=None;self.clone_cache_image=None
        saved,current_id,active=snapshot
        state=copy.deepcopy(saved)
        # Editing a region does not require reloading every thumbnail.
        if [e['id'] for e in state]==[e['id'] for e in self.ordered()]:
            self.entries={e['id']:e for e in state}
        else:
            self.restore_list(state)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole)==current_id:
                self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect); break
        entry=self.current()
        self.canvas.active=min(active,len(entry['regions'])-1) if entry else -1
        # Undo restores image edits only; keep the user's current tool settings.
        self.original.setChecked(False); self.render(); self.renumber(); self.dirty=True
    def restore_list(self,entries):
        wanted={entry['id'] for entry in entries}
        scroll=self.list.verticalScrollBar().value()
        self.list.blockSignals(True);self.list.setUpdatesEnabled(False)
        try:
            for row in reversed(range(self.list.count())):
                if self.list.item(row).data(Qt.ItemDataRole.UserRole) not in wanted:self.list.takeItem(row)
            self.entries={entry['id']:entry for entry in entries}
            existing={self.list.item(row).data(Qt.ItemDataRole.UserRole):self.list.item(row) for row in range(self.list.count())}
            for row,entry in enumerate(entries):
                item=existing.get(entry['id'])
                if item is None:self.insert_entry(entry,row)
                elif self.list.row(item)!=row:
                    item=self.list.takeItem(self.list.row(item));self.list.insertItem(row,item)
            self.list.doItemsLayout();self.list.verticalScrollBar().setValue(scroll)
        finally:
            self.list.blockSignals(False);self.list.setUpdatesEnabled(True)
        self.selection_changed()
    def populate(self,entries):
        self.list.clear(); self.entries={}
        for entry in entries: self.insert_entry(entry)
        self.renumber()
        if self.list.count(): self.list.setCurrentRow(0)
        else: self.canvas.pixmap=None; self.canvas.update()
    def insert_entry(self,entry,row=None):
        entry.setdefault('main_selected',False)
        entry.setdefault('clones',[])
        self.entries[entry['id']]=entry
        item=QListWidgetItem(Path(entry['path']).name); item.setData(Qt.ItemDataRole.UserRole,entry['id']); item.setToolTip(entry['path'])
        if row is None:self.list.addItem(item)
        else:self.list.insertItem(row,item)
        path=entry['path']
        try:
            info=Path(path).stat();key=(path,info.st_size,info.st_mtime_ns)
        except OSError:key=(path,None,None)
        if key in self.thumb_cache:
            self.thumb_cache.move_to_end(key);item.setIcon(QPixmap.fromImage(self.thumb_cache[key]));return
        if key in self.thumb_waiters:
            self.thumb_waiters[key].add(entry['id']);return
        self.thumb_waiters[key]={entry['id']}
        self.run_job(self.pool,lambda:self.load_thumb(path),lambda result:self.thumb_ready(key,result))
    @staticmethod
    def load_thumb(path):
        image=read_pixels(path); image.thumbnail((140,110)); return to_qimage(image)
    def thumb_ready(self,key,result):
        waiters=self.thumb_waiters.pop(key,set())
        if not result[0]:
            if any(eid in self.entries for eid in waiters):self.status.setText('읽기 실패: '+key[0])
            return
        image=result[1];self.thumb_cache[key]=image;self.thumb_cache_bytes+=image.sizeInBytes()
        while self.thumb_cache_bytes>128*1024*1024 and len(self.thumb_cache)>1:
            _,old=self.thumb_cache.popitem(last=False);self.thumb_cache_bytes-=old.sizeInBytes()
        for row in range(self.list.count()):
            item=self.list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) in waiters:item.setIcon(QPixmap.fromImage(image))
    def add_dialog(self):
        files,_=QFileDialog.getOpenFileNames(self,'그림 추가','','Images (*.webp *.png *.jpg *.jpeg *.bmp *.tif *.tiff)'); self.add_paths(files)
    def folder_dialog(self):
        path=QFileDialog.getExistingDirectory(self,'그림 폴더'); self.add_paths([path] if path else [])
    def add_paths(self,paths,insertion_row=None):
        expanded=[]
        for path in paths:
            p=Path(path)
            expanded.extend(sorted(p.rglob('*')) if p.is_dir() else [p])
        known={e['path'] for e in self.entries.values()}
        paths=[str(p.resolve()) for p in expanded if p.is_file() and p.suffix.lower() in EXTENSIONS]
        paths=list(dict.fromkeys(p for p in paths if p not in known))
        if not paths:return
        self.snapshot(f'그림 추가 · {len(paths)}장')
        if insertion_row is None:
            for path in paths:self.insert_entry({'id':uuid.uuid4().hex,'path':path,'regions':[]})
            self.renumber()
            if self.list.currentRow()<0:self.list.setCurrentRow(0)
            return
        row=max(0,min(self.list.count(),insertion_row))
        self.list.blockSignals(True);self.list.setUpdatesEnabled(False)
        try:
            for offset,path in enumerate(paths):self.insert_entry({'id':uuid.uuid4().hex,'path':path,'regions':[]},row+offset)
            self.list.clearSelection()
            self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.NoUpdate)
            for offset in range(len(paths)):self.list.item(row+offset).setSelected(True)
            self.list.selection_anchor=self.list.item(row).data(Qt.ItemDataRole.UserRole)
        finally:
            self.list.blockSignals(False);self.list.setUpdatesEnabled(True)
        self.list.scrollToItem(self.list.item(row));self.list.setFocus(Qt.FocusReason.OtherFocusReason)
        self.renumber();self.selection_changed()
    def renumber(self):
        self.update_selection_count()
        for i in range(self.list.count()):
            item=self.list.item(i); entry=self.entries[item.data(Qt.ItemDataRole.UserRole)]
            item.setText(f'{i+1:03d}  '+Path(entry['path']).name+('  [도장]' if entry.get('clones') else '')+('  [컷]' if entry.get('composition') else ''))
            item.setData(MOSAIC_ROLE,bool(entry['regions']))
            item.setData(MAIN_ROLE,bool(entry.get('main_selected',False)))
            item.setToolTip(entry['path']+(f'\n모자이크 적용 · {len(entry["regions"])}개 영역' if entry['regions'] else '\n모자이크 없음'))
        self.status.setText(f'총 {self.list.count()}장 · 모자이크 {sum(bool(e["regions"]) for e in self.entries.values())}장 · 메인 {sum(bool(e.get("main_selected")) for e in self.entries.values())}장')
    def order_changed(self):self.dirty=True; self.renumber()
    def remove_selected(self):
        rows=sorted(self.list.row(item) for item in self.list.selectedItems())
        if not rows:return
        # Pick by the current visual order, never by Qt's implicit selection
        # changes while individual rows are being removed.
        next_row=rows[0]
        self.snapshot(f'목록에서 제외 · {len(rows)}장'); self.list.blockSignals(True)
        for row in reversed(rows):
            item=self.list.takeItem(row)
            self.entries.pop(item.data(Qt.ItemDataRole.UserRole),None)
        self.list.clearSelection()
        if self.list.count():
            next_row=min(next_row,self.list.count()-1)
            self.list.setCurrentRow(next_row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
            self.list.item(next_row).setSelected(True)
            self.list.scrollToItem(self.list.item(next_row))
        else:
            self.list.setCurrentRow(-1)
        self.list.blockSignals(False)
        self.renumber(); self.selection_changed()
    def navigate(self,step):
        if not self.list.count():return
        row=max(0,min(self.list.count()-1,self.list.currentRow()+step))
        self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
        item=self.list.item(row)
        self.list.selection_anchor=item.data(Qt.ItemDataRole.UserRole)
        self.list.scrollToItem(item)
        self.list.viewport().update()
    def sync_main_check(self):
        entry=self.current()
        self.main_check.blockSignals(True)
        self.main_check.setEnabled(entry is not None)
        self.main_check.setChecked(bool(entry and entry.get('main_selected',False)))
        self.main_check.blockSignals(False)
    def update_selection_count(self):
        count=len(self.list.selectedItems())
        self.selection_count.setText(f'선택 {count}장')
        if hasattr(self,'bottom_selection_count'):self.bottom_selection_count.setText(f'선택 {count}장 / 전체 {self.list.count()}장')
    def thumbnail_context_menu(self,pos):
        row=self.list.row_at(pos)
        if row>=0 and not self.list.item(row).isSelected():
            self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
        ids=[item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        if not ids:return
        menu=QMenu(self.list)
        mark=menu.addAction(f'선택한 {len(ids)}장 메인으로 지정')
        unmark=menu.addAction(f'선택한 {len(ids)}장 메인 지정 해제')
        mark.triggered.connect(lambda:self.set_main_for_ids(ids,True))
        unmark.triggered.connect(lambda:self.set_main_for_ids(ids,False))
        menu.exec(self.list.viewport().mapToGlobal(pos))
    def set_main_for_ids(self,ids,checked):
        targets=[self.entries[eid] for eid in set(ids) if eid in self.entries and bool(self.entries[eid].get('main_selected'))!=checked]
        if not targets:return
        self.snapshot(('메인 일괄 지정' if checked else '메인 일괄 해제')+f' · {len(targets)}장')
        for entry in targets:entry['main_selected']=checked
        self.sync_main_check();self.renumber()
        self.status.setText(f'{len(targets)}장 메인 '+('지정 완료' if checked else '지정 해제 완료')+' · Ctrl+Z로 일괄 취소')
    def toggle_main(self,checked):
        entry=self.current()
        if not entry or bool(entry.get('main_selected',False))==checked:return
        self.snapshot('메인 지정' if checked else '메인 해제');entry['main_selected']=checked;self.renumber()
        self.list.setFocus(Qt.FocusReason.OtherFocusReason)
    def selection_changed(self,*args):
        self.clone_timer.stop();self.clone_live=None;self.clone_live_entry=None
        self.clone_cache_key=None;self.clone_cache_image=None
        self.sync_main_check()
        self.canvas.reset_view()
        self.canvas.clone_source=None;self.canvas.drawing_clone=False
        self.canvas.active=-1; self.original.setChecked(False)
        entry=self.current()
        self.canvas.pixmap=None; self.canvas.regions=[]; self.canvas.update()
        if not entry:self.title.setText('그림을 선택하세요'); return
        self.title.setText(Path(entry['path']).name)
        self.request_preview(entry['path'],True)
        row=self.list.currentRow()
        for offset in [-1,1,2]:
            if 0<=row+offset<self.list.count():
                neighbor=self.entries.get(self.list.item(row+offset).data(Qt.ItemDataRole.UserRole))
                if neighbor: self.request_preview(neighbor['path'],False)
    def request_preview(self,path,urgent):
        if path in self.cache:
            self.cache.move_to_end(path)
            if urgent:self.render()
            return
        if path in self.pending:return
        self.pending.add(path)
        self.run_job(self.preview_pool,lambda:self.load_preview(path),lambda result:self.preview_ready(path,result),10 if urgent else 0)
    @staticmethod
    def load_preview(path):
        image=read_pixels(path); image.thumbnail((1920,1920)); return image
    def preview_ready(self,path,result):
        self.pending.discard(path)
        if result[0]:
            self.cache[path]=result[1]
            while len(self.cache)>16:self.cache.popitem(last=False)
        entry=self.current()
        if entry and entry['path']==path:
            if result[0]:self.render()
            else:self.title.setText('읽기 실패: '+result[1])
    def clone_key(self,entry,image):
        return (id(entry),id(image),len(entry.get('clones',[])))
    def composed_image(self,entry,image):
        composition=entry.get('composition')
        if not composition:return image
        key=(id(entry),id(image),id(composition))
        if key!=self.composition_cache_key:
            self.composition_cache_image=render_composition(image,composition);self.composition_cache_key=key
        return self.composition_cache_image
    def copy_for_cut(self):
        entry=self.current()
        if not entry:return
        try:
            self.cut_clipboard=pixel_asset(render_entry(read_pixels(entry['path']),entry))
            self.status.setText('모자이크 포함 그림 복사 완료 · 대상 썸네일을 선택하고 컷 편집을 여세요.')
        except Exception as exc:QMessageBox.warning(self,'컷 복사 실패',str(exc))
    def apply_composition(self,composition):
        entry=self.current()
        if not entry or composition==entry.get('composition'):return
        validate_composition(composition);self.snapshot('컷 편집 / 합성')
        entry['composition']=copy.deepcopy(composition)
        self.clone_cache_key=None;self.composition_cache_key=None;self.render();self.renumber()
    def edit_cuts(self):
        entry=self.current()
        if not entry:return
        from cut_editor import CutEditor
        dialog=None
        try:
            dialog=CutEditor(entry,self.ordered(),[self.list.item(i).icon() for i in range(self.list.count())],self.cut_clipboard,self)
            shortcuts=[self.undo_shortcut]+self.redo_shortcuts
            for shortcut in shortcuts:shortcut.setEnabled(False)
            try:result=dialog.exec()
            finally:
                for shortcut in shortcuts:shortcut.setEnabled(True)
            self.cut_clipboard=dialog.clipboard
            if result:self.apply_composition(dialog.composition)
        except Exception as exc:QMessageBox.warning(self,'컷 편집 실패',str(exc))
        finally:
            if dialog is not None:dialog.timer.stop();dialog.deleteLater()
    def committed_clones(self,entry,image):
        key=self.clone_key(entry,image)
        if key!=self.clone_cache_key:
            self.clone_cache_image=render_clones(image,entry.get('clones',[]));self.clone_cache_key=key
        return self.clone_cache_image
    def flush_clone_preview(self,finish=False):
        entry=self.current()
        if self.clone_live is None or entry is not self.clone_live_entry:return
        self.clone_timer.stop()
        self.clone_live.update(entry['clones'][-1]['points'])
        if finish:
            image=self.composed_image(entry,self.cache.get(entry['path']))
            self.clone_cache_image=self.clone_live.result;self.clone_cache_key=self.clone_key(entry,image)
            self.clone_live=None;self.clone_live_entry=None
        self.render()
    def render(self,*args):
        self.sync_main_check()
        entry=self.current()
        if not entry or entry['path'] not in self.cache:return
        image=self.cache[entry['path']]
        if not self.original.isChecked():
            image=self.composed_image(entry,image)
            cloned=self.clone_live.result if self.clone_live is not None and entry is self.clone_live_entry else self.committed_clones(entry,image)
            image=render_regions(cloned,entry['regions']) if entry['regions'] else cloned
        self.canvas.pixmap=QPixmap.fromImage(to_qimage(image))
        self.canvas.regions=[] if self.original.isChecked() else entry['regions']; self.canvas.update()
    def region_event(self,event):
        entry=self.current()
        if not entry or self.original.isChecked():return
        if event[0]=='clone_missing':
            self.status.setText('복제 도장: Alt+클릭으로 복사할 기준점을 먼저 선택하세요.');return
        if event[0]=='clone_source':
            self.status.setText('도장 기준점 선택 완료 · 지울 부위를 드래그하세요.');return
        if event[0]=='clone_start':
            image=self.composed_image(entry,self.cache.get(entry['path'])) if entry['path'] in self.cache else None
            if image is None:return
            self.snapshot('복제 도장')
            base=self.committed_clones(entry,image)
            entry.setdefault('clones',[]).append(event[1]);self.canvas.active=-1
            self.clone_live=ClonePreview(base,event[1]);self.clone_live_entry=entry
            self.clone_live.update(event[1]['points'])
        elif event[0] in ('clone_move','clone_end'):
            if not entry.get('clones'):return
            entry['clones'][-1]['points']=event[1]
            if self.clone_live is not None and entry is self.clone_live_entry:
                if event[0]=='clone_end':self.flush_clone_preview(True)
                elif not self.clone_timer.isActive():self.clone_timer.start(16)
                return
        elif event[0]=='brush_start':
            self.snapshot('브러시 모자이크 추가')
            region={'kind':'brush','points':event[1]['points'],'radius':event[1]['radius'],'strength':self.strength.value()}
            self.brush_bounds(region); entry['regions'].append(region); self.canvas.active=len(entry['regions'])-1
        elif event[0]=='brush_move':
            if not 0<=self.canvas.active<len(entry['regions']):return
            region=entry['regions'][self.canvas.active]
            region['points']=event[1]; self.brush_bounds(region)
        elif event[0]=='add':
            self.snapshot('박스 모자이크 추가'); entry['regions'].append({'rect':event[1],'strength':self.strength.value()}); self.canvas.active=len(entry['regions'])-1
        else:
            self.canvas.active=event[1]
            if event[1]>=0:
                self.strength.blockSignals(True); self.strength.setValue(entry['regions'][event[1]]['strength']); self.strength.blockSignals(False); self.value.setText(str(self.strength.value()))
        self.render(); self.renumber()
    def brush_bounds(self,region):
        image=self.cache.get(self.current()['path'])
        aspect=image.width/image.height if image else 1
        radius=region['radius']; points=region['points']
        region['rect']=[max(0,min(p[0] for p in points)-radius),max(0,min(p[1] for p in points)-radius*aspect),
                        min(1,max(p[0] for p in points)+radius),min(1,max(p[1] for p in points)+radius*aspect)]
    def begin_strength_change(self):
        self.strength_drag_recorded=False
    def strength_changed(self,value):
        self.value.setText(str(value));entry=self.current();index=self.canvas.active
        if not entry or not 0<=index<len(entry['regions']):return
        if entry['regions'][index]['strength']==value:return
        if not self.strength.isSliderDown() or not self.strength_drag_recorded:
            self.snapshot('모자이크 강도 변경')
            self.strength_drag_recorded=self.strength.isSliderDown()
        entry['regions'][index]['strength']=value;self.dirty=True;self.render()
    def clear_mosaics(self,ids):
        targets=[self.entries[eid] for eid in set(ids) if eid in self.entries and self.entries[eid]['regions']]
        if not targets:
            self.status.setText('지울 모자이크가 없습니다.');return
        self.snapshot(f'모자이크 초기화 · {len(targets)}장')
        for entry in targets:entry['regions']=[]
        self.canvas.active=-1;self.canvas.start=None;self.canvas.end=None;self.canvas.drawing_brush=False
        self.original.setChecked(False);self.render();self.renumber()
        self.status.setText(f'{len(targets)}장의 모자이크를 모두 지웠습니다. 도장 보정은 유지됩니다. Ctrl+Z로 복원')
    def batch_strength_dialog(self):
        ids=[item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        entries=[self.entries[eid] for eid in ids if self.entries[eid]['regions']]
        count=sum(len(entry['regions']) for entry in entries)
        if not count:
            self.status.setText('모자이크가 있는 사진을 먼저 선택하세요. Ctrl+A로 전체 선택할 수 있습니다.')
            return
        strength,accepted=QInputDialog.getInt(self,'모자이크 강도 일괄 변경',
            f'선택한 {len(ids)}장 중 모자이크가 있는 {len(entries)}장 · {count}개 영역\n'
            '박스와 브러시의 위치·범위는 유지하고 모든 영역의 강도만 변경합니다.\n새 강도 (2~100):',
            self.strength.value(),2,100,1)
        if accepted:self.apply_batch_strength(ids,strength)
    def apply_batch_strength(self,ids,strength):
        if not 2<=strength<=100:raise ValueError('강도는 2~100 범위여야 합니다.')
        entries=[self.entries[eid] for eid in set(ids) if eid in self.entries and self.entries[eid]['regions']]
        changed=[entry for entry in entries if any(r['strength']!=strength for r in entry['regions'])]
        if not changed:
            self.status.setText('변경할 모자이크 강도가 없습니다.');return
        self.snapshot(f'모자이크 강도 일괄 변경 · {len(changed)}장')
        for entry in changed:
            for region in entry['regions']:region['strength']=strength
        # Updating the slider here must not create a separate edit or history entry.
        self.strength.blockSignals(True);self.strength.setValue(strength);self.strength.blockSignals(False)
        self.value.setText(str(strength));self.original.setChecked(False);self.render();self.renumber()
        self.status.setText(f'{len(changed)}장 · {sum(len(e["regions"]) for e in changed)}개 영역 강도를 {strength}로 변경했습니다. Ctrl+Z로 일괄 취소')
    def remove_region(self):
        entry=self.current(); i=self.canvas.active
        if entry and 0<=i<len(entry['regions']):
            self.snapshot('모자이크 영역 삭제'); entry['regions'].pop(i); self.canvas.active=-1; self.render(); self.renumber()
    def save_project(self):
        if self.project:return self.write_project(self.project)
        return self.save_project_as()
    def save_project_as(self):
        path,_=QFileDialog.getSaveFileName(self,'다른 이름으로 작업 저장',self.project or '작업.photo.json','Photo project (*.photo.json)')
        if path and not path.lower().endswith('.photo.json'):path+='.photo.json'
        return self.write_project(path)
    def write_project(self,path):
        if not path:return False
        try:
            entry=self.current()
            view={'current_id':entry['id'] if entry else None,'scroll':self.list.verticalScrollBar().value()}
            temp=Path(path+'.tmp'); temp.write_text(json.dumps({'version':1,'images':self.ordered(),'view':view},ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)
            self.project=str(Path(path).resolve()); self.dirty=False;self.remember_project(self.project); self.status.setText('작업 저장 완료');return True
        except Exception as exc:
            QMessageBox.warning(self,'저장 실패',str(exc));return False
    def confirm_discard(self):
        if not self.dirty:return True
        buttons=QMessageBox.StandardButton
        box=QMessageBox(QMessageBox.Icon.Question,'작업 저장',
            '저장하지 않은 변경 사항이 있습니다. 저장할까요?',buttons.Save|buttons.Discard|buttons.Cancel,self)
        box.button(buttons.Save).setText('저장')
        box.button(buttons.Discard).setText('저장하지 않음')
        box.button(buttons.Cancel).setText('취소')
        box.setDefaultButton(buttons.Save);box.setEscapeButton(buttons.Cancel)
        result=box.exec()
        if result==buttons.Save:return self.save_project()
        return result==buttons.Discard
    def load_project(self):
        path,_=QFileDialog.getOpenFileName(self,'작업 열기','','Photo project (*.photo.json)')
        if path:return self.open_project(path)
        return False
    def open_project(self,path):
        if not self.confirm_discard():return False
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8')); entries=data['images']
            if data.get('version')!=1:raise ValueError('지원하지 않는 작업 파일입니다.')
            for e in entries:
                if 'composition' in e:validate_composition(e['composition'],check_images=True)
                if not isinstance(e.get('main_selected',False),bool):raise ValueError('잘못된 메인 선택 상태')
                if not isinstance(e['path'],str) or not isinstance(e['regions'],list):raise ValueError('잘못된 작업 파일')
                if not isinstance(e.get('clones',[]),list):raise ValueError('잘못된 도장 데이터')
                for stroke in e.get('clones',[]):
                    def valid_point(point):return isinstance(point,(list,tuple)) and len(point)==2 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in point)
                    if not valid_point(stroke.get('source')) or not isinstance(stroke.get('points'),list) or not stroke['points'] or not all(valid_point(point) for point in stroke['points']):raise ValueError('잘못된 도장 좌표')
                    if not 0<stroke.get('radius',0)<=.1 or not 0<=stroke.get('softness',.5)<=1:raise ValueError('잘못된 도장 크기')
                for r in e['regions']:
                    if len(r['rect'])!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in r['rect']) or not 2<=r['strength']<=100:raise ValueError('잘못된 모자이크 영역')
                    if r.get('kind')=='brush':
                        if not isinstance(r.get('points'),list) or not r['points'] or not 0<r.get('radius',0)<=.1:raise ValueError('잘못된 브러시 영역')
                        if not all(len(point)==2 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in point) for point in r['points']):raise ValueError('잘못된 브러시 좌표')
            self.populate(entries); self.history=[]; self.history_labels=[]; self.redo_stack=[];self.snapshot_cache={};self.update_history_controls(); self.project=str(Path(path).resolve()); self.dirty=False
            view=data.get('view',{})
            if isinstance(view,dict):
                for row in range(self.list.count()):
                    if self.list.item(row).data(Qt.ItemDataRole.UserRole)==view.get('current_id'):
                        self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
                        self.list.scrollToItem(self.list.item(row));break
                self.list.doItemsLayout()
                if isinstance(view.get('scroll'),int):self.list.verticalScrollBar().setValue(view['scroll'])
            self.remember_project(self.project);return True
        except Exception as exc:
            QMessageBox.warning(self,'열기 실패',str(exc));return False
    def choose_export_folder(self):
        folder=QFileDialog.getExistingDirectory(self,'결과를 저장할 상위 폴더',self.export_folder)
        if not folder:return False
        self.export_folder=folder;self.settings.setValue('export/folder',folder)
        self.export_folder_label.setText(folder);self.export_folder_label.setToolTip(folder)
        return True
    def confirm_output_replacement(self,paths):
        if isinstance(paths,(str,Path)):paths=[paths]
        path_text='\n'.join(str(path) for path in paths)
        buttons=QMessageBox.StandardButton
        box=QMessageBox(QMessageBox.Icon.Warning,'기존 출력 내용 삭제',
            f'{path_text}\n위에 표시한 출력 폴더만 삭제하고 새로 내보낼까요?\n체크하지 않은 출력 폴더와 그 밖의 파일은 유지됩니다.',buttons.Yes|buttons.No,self)
        box.button(buttons.Yes).setText('예');box.button(buttons.No).setText('아니오')
        box.setDefaultButton(buttons.No);box.setEscapeButton(buttons.No)
        return box.exec()==buttons.Yes
    def export(self):
        if not self.entries or self.busy:return
        outputs={key:check.isChecked() for key,check in self.output_checks.items()}
        if not any(outputs.values()):
            self.status.setText('내보낼 항목을 하나 이상 체크하세요.');return
        if outputs['main'] and not outputs['cen'] and not outputs['uncen'] and not any(e.get('main_selected') for e in self.entries.values()):
            self.status.setText('메인 게시용으로 체크한 그림이 없습니다.');return
        if not self.export_folder or not Path(self.export_folder).is_dir():
            if not self.choose_export_folder():return
        folder=self.export_folder
        stem=self.export_name.text()
        stem=stem.strip()
        if not stem or stem in {'.','..'} or any(c in stem for c in '<>:"/\\|?*') or stem.endswith('.'):
            QMessageBox.warning(self,'폴더 이름','사용할 수 없는 폴더 이름입니다.');return
        reserved={'CON','PRN','AUX','NUL'}|{f'COM{i}' for i in range(1,10)}|{f'LPT{i}' for i in range(1,10)}
        if stem.split('.')[0].upper() in reserved or any(ord(c)<32 for c in stem):
            QMessageBox.warning(self,'폴더 이름','사용할 수 없는 폴더 이름입니다.');return
        self.settings.setValue('export/name',stem)
        try:
            destination=prepare_output(folder,stem,[entry['path'] for entry in self.entries.values()],self.confirm_output_replacement,outputs)
            if destination is None:
                self.status.setText('내보내기를 취소했습니다. 기존 파일은 유지됩니다.');return
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'출력 폴더 준비 실패',str(exc));return
        entries=copy.deepcopy(self.ordered()); fmt=self.format.currentText(); ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
        self.busy=True; self.export_button.setEnabled(False); self.progress.setRange(0,len(entries)); self.progress.setValue(0); self.progress.show(); self.errors=[]; self.exported_main=0;self.exported_files=0
        self.export_next(entries,0,destination,fmt,ext,stem,outputs)
    def export_next(self,entries,index,destination,fmt,ext,stem,outputs):
        if index==len(entries):
            self.busy=False; self.export_button.setEnabled(True); self.progress.hide()
            message=f'{self.exported_files}개 파일 저장 완료\n{destination}'
            if outputs['cen']:message+=f'\n{stem}_cen: 모자이크 처리본'
            if outputs['uncen']:message+=f'\n{stem}_uncen: 원본용 · 메타데이터만 제거'
            if self.exported_main:message+=f'\n{stem}_main: 메인 게시용 {self.exported_main}장'
            message+='\n출력 파일 메타데이터 제거 검증 완료'
            if self.errors:message+='\n\n실패:\n'+'\n'.join(self.errors[:10])
            QMessageBox.information(self,'내보내기 결과',message); return
        def complete(result):
            if not result[0]:self.errors.append(Path(entries[index]['path']).name+': '+result[1])
            else:
                self.exported_files+=len(result[1])
                if outputs['main'] and entries[index].get('main_selected',False):self.exported_main+=1
            self.progress.setValue(index+1); self.export_next(entries,index+1,destination,fmt,ext,stem,outputs)
        self.run_job(self.export_pool,lambda:export_pair(entries[index],index+1,destination,fmt,stem,outputs,self.exported_main+1),complete)
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'내보내기 중','내보내기가 끝난 후 종료하세요.'); event.ignore(); return
        if not self.confirm_discard():event.ignore(); return
        self.settings.setValue('layout/splitter',self.splitter.saveState())
        self.settings.setValue('layout/windowState',self.saveState())
        self.settings.setValue('layout/previewVertical',self.preview_splitter.saveState())
        self.settings.sync()
        self.pool.waitForDone(); self.preview_pool.waitForDone(); event.accept()

if __name__=='__main__':
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('wktmq36.PhotoOrganizer.Desktop')
    app=QApplication(sys.argv); app.setStyle('Fusion')
    app.setApplicationName('Photo');app.setOrganizationName('PhotoOrganizer')
    app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'photo.png')))
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    if font_path.exists():
        font_id=QFontDatabase.addApplicationFont(str(font_path))
        families=QFontDatabase.applicationFontFamilies(font_id)
        if families: app.setFont(QFont(families[0], 10))
    app.setStyleSheet('QWidget {font-family: "Malgun Gothic"; font-size: 12px;} QPushButton {padding: 8px 12px;} QListWidget {background:#202630;color:#eef2f8;} QListWidget::item:selected {background:#355e89;}')
    window=Window(); window.show()
    if '--smoke-test' in sys.argv:
        assert not app.windowIcon().isNull() and not window.windowIcon().isNull()
        if sys.platform=='win32':
            app_id=ctypes.c_wchar_p()
            assert ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(ctypes.byref(app_id))==0
            assert app_id.value=='wktmq36.PhotoOrganizer.Desktop'
            ctypes.windll.ole32.CoTaskMemFree(app_id)
        from PIL import Image
        sample=to_qimage(Image.new('RGBA',(32,32),(12,34,56,255)))
        assert sample.pixelColor(0,0).red()==12
        window.canvas.pixmap=QPixmap.fromImage(sample)
        window.canvas.update()
        from PySide6.QtTest import QTest
        from PySide6.QtCore import QPoint
        import tempfile
        smoke_folder=tempfile.TemporaryDirectory()
        smoke_paths=[]
        for index,color in enumerate(['red','green','blue']):
            path=Path(smoke_folder.name)/f'{index}.png'
            Image.new('RGB',(80,60),color).save(path); smoke_paths.append(str(path))
        window.add_paths(smoke_paths); app.processEvents()
        start=window.list.visualItemRect(window.list.item(0)).center()
        rect=window.list.visualItemRect(window.list.item(2))
        finish=QPoint(rect.right()-8,rect.center().y())
        viewport=window.list.viewport()
        QTest.mousePress(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
        QTest.mouseMove(viewport,finish,50)
        assert window.list.dragging
        QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,finish)
        assert [entry['path'] for entry in window.ordered()]==smoke_paths[1:]+smoke_paths[:1]
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDragEnterEvent,QDragMoveEvent,QDropEvent
        external=Path(smoke_folder.name)/'external.png';Image.new('RGB',(80,60),'yellow').save(external)
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(external))])
        rect=window.list.cell_rect(1);pos=QPoint(rect.left()+3,rect.center().y())
        for event in (QDragEnterEvent(pos,Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier),
                      QDragMoveEvent(pos,Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier),
                      QDropEvent(QPointF(pos),Qt.DropAction.CopyAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)):
            QApplication.sendEvent(viewport,event);assert event.isAccepted()
        assert [entry['path'] for entry in window.ordered()]==[smoke_paths[1],str(external),smoke_paths[2],smoke_paths[0]]
        from cut_editor import CutEditor
        cut_dialog=CutEditor(window.current(),window.ordered(),[window.list.item(i).icon() for i in range(window.list.count())],parent=window)
        cut_dialog.sources.setCurrentRow(0);cut_dialog.copy_source();cut_dialog.pick((0,[.5,.5],'vertical'));cut_dialog.paste()
        cut_dialog.scale_layer(1);cut_dialog.fit(True)
        cut_dialog.add_cell([.2,.2,.8,.8]);cut_dialog.paste()
        cut_dialog.source_canvas.selection=[.25,.25,.75,.75];cut_dialog.source_selected(cut_dialog.source_canvas.selection)
        cut_dialog.fill_original_resolution();cut_dialog.apply()
        window.apply_composition(cut_dialog.composition)
        assert window.current()['composition']['cells'][0].get('asset')
        cut_result=render_entry(read_pixels(window.current()['path']),window.current())
        assert cut_result.size==(80,60) and cut_result.getpixel((10,30))[:3]==(0,128,0)
        for index,entry in enumerate(window.ordered()):
            export_image(entry,Path(smoke_folder.name)/f'output{index}.png','PNG')
        window.dirty=False
        QTimer.singleShot(1000,app.quit)
    sys.exit(app.exec())
