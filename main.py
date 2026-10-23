import sys, json, uuid, copy, time
from datetime import datetime
from ui_theme import apply_theme, action_icon
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QRect, QRectF, QPointF, Signal, QObject, QRunnable, QThreadPool, QTimer, QMimeData, QItemSelectionModel, QSettings, QEvent
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QAction, QKeySequence, QFontDatabase, QFont, QShortcut, QDrag, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QFileDialog,
    QMessageBox, QSpinBox, QAbstractSpinBox, QComboBox, QProgressBar, QScrollArea, QStyledItemDelegate, QLayout, QInputDialog, QCheckBox, QLineEdit, QMenu, QDockWidget, QToolButton, QButtonGroup, QStyle, QStackedWidget, QGridLayout, QSizePolicy)
from exporting import prepare_output
from mega_share import MegaClient,find_client,create_package,upload_package
from imaging import EXTENSIONS, read_pixels, render_regions, render_entry, render_clones, ClonePreview, export_image, export_banner, export_pair, crop_base, edit_layers, all_regions, validate_edits
from composition import paired_asset,pixel_asset,render_composition,validate_composition

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

class NumericControl(QSpinBox):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.wheel_remainder=0
        self.setSingleStep(1);self.setFixedWidth(70);self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
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
            button=QToolButton();button.setIcon(tool_icon(index));button.setIconSize(QSize(23,23));button.setCheckable(True)
            button.setToolTip(label);button.setAccessibleName(label);button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(32,30);self.group.addButton(button,index);layout.addWidget(button);self.buttons.append(button)
        self.buttons[0].setChecked(True)
        self.setObjectName('toolPicker')
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
            if self.item(row).isHidden():continue
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
            for i in range(min(anchor,row),max(anchor,row)+1):
                if not self.item(i).isHidden():self.item(i).setSelected(True)
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
            if self.item(row).isHidden():continue
            rect=self.visualItemRect(self.item(row))
            bands.setdefault(rect.top(),[]).append((row,rect))
        if not bands:self.drop_marker=None;return self.count()
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
            if self.item(row).isHidden():continue
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
        if getattr(self,'drop_marker',None) is not None:
            x,top,bottom=self.drop_marker
            painter.drawLine(x,top,x,bottom)
            painter.drawLine(x-5,top,x+5,top)
            painter.drawLine(x-5,bottom,x+5,bottom)
    def selectAll(self):
        blocked=self.blockSignals(True)
        for row in range(self.count()):self.item(row).setSelected(not self.item(row).isHidden())
        self.blockSignals(blocked)
        if not blocked:self.itemSelectionChanged.emit()
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
        super().__init__();self._placement_ready=False;self._restoring_placement=False;self._last_window_geometry=None;self._minimized_geometry=None; self.setWindowTitle('Photo · 그림 정리와 편집 v0.2.61'); self.resize(1400,900)
        self.setWindowIcon(QIcon(str(Path(__file__).parent/'assets'/'photo.png')))
        self.settings=QSettings('PhotoOrganizer','Photo')
        legacy_size=self.settings.value('tools/size',50,type=int)
        self.tool_sizes={name:max(5,min(200,self.settings.value('tools/sizes/'+name,legacy_size,type=int))) for name in ['box','brush','clone']}
        self.export_folder=str(self.settings.value('export/folder',''))
        try:self.recent_projects=json.loads(str(self.settings.value('projects/recent','[]')))
        except (ValueError,TypeError):self.recent_projects=[]
        if not isinstance(self.recent_projects,list):self.recent_projects=[]
        self.recent_projects=[path for path in self.recent_projects if isinstance(path,str)]
        self.entries={}; self.cache=OrderedDict(); self.pending=set(); self.history=[]; self.history_labels=[]; self.redo_stack=[]; self.snapshot_cache={};  self.dirty=False; self.project=None
        self.clone_cache_key=None;self.clone_cache_image=None;self.clone_live=None;self.clone_live_entry=None
        self.cut_clipboard=None;self.composition_cache_key=None;self.composition_cache_image=None
        self.cut_editor=None;self.crop_editor=None;self.navigation_actions=[];self.pending_project_name='작업'
        self.clone_timer=QTimer(self);self.clone_timer.setSingleShot(True);self.clone_timer.timeout.connect(self.flush_clone_preview)
        self.thumb_cache=OrderedDict();self.thumb_waiters={};self.thumb_cache_bytes=0
        self.pool=QThreadPool(self); self.pool.setMaxThreadCount(4)
        self.preview_pool=QThreadPool(self); self.preview_pool.setMaxThreadCount(2)
        self.export_pool=QThreadPool(self); self.export_pool.setMaxThreadCount(1)
        self.jobs=set(); self.errors=[]; self.busy=False
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root);layout.setContentsMargins(4,4,4,4);layout.setSpacing(4)
        self.header=QWidget();self.header.setObjectName("header");self.header_grid=QGridLayout(self.header);self.header_grid.setContentsMargins(0,0,0,0);self.header_grid.setSpacing(4)
        self.header.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);self.header_grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(self.header);self.header_stacked=None
        self.action_controls=QWidget();top=QHBoxLayout(self.action_controls);top.setContentsMargins(0,0,0,0);top.setSpacing(4)
        self.header_grid.addWidget(self.action_controls,0,0,1,2)
        for label,fn in [('새 작업',self.new_project),('파일 추가',self.add_dialog),('폴더 추가',self.folder_dialog),('작업 열기',self.load_project),('작업 저장',self.save_project),('다른 이름으로 저장',self.save_project_as),('실행 취소',self.undo),('다시 실행',self.redo),('목록에서 제외',self.remove_selected)]:
            button=QPushButton(label); button.clicked.connect(fn); top.addWidget(button)
            icons={'새 작업':'file','파일 추가':'file','폴더 추가':'folder','작업 열기':'folder',
                   '작업 저장':'save','다른 이름으로 저장':'save','목록에서 제외':'trash','실행 취소':'undo','다시 실행':'redo'}
            button.setIcon(action_icon(icons[label]));button.setIconSize(QSize(16,16))
            if label=='실행 취소':self.undo_button=button
            elif label=='다시 실행':self.redo_button=button
        self.history_dock=QDockWidget('저장한 작업',self);self.history_dock.setObjectName('photoHistoryDock')
        self.history_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea|Qt.DockWidgetArea.RightDockWidgetArea)
        history_body=QWidget();history_layout=QVBoxLayout(history_body)
        self.history_summary=QLabel('저장한 작업 0개');history_layout.addWidget(self.history_summary)
        self.history_list=QListWidget();self.history_list.setObjectName('projectList');self.history_list.setMinimumWidth(220);history_layout.addWidget(self.history_list)
        self.history_list.itemClicked.connect(self.open_recent_project)
        add_project_button=QPushButton('작업 파일 추가');add_project_button.clicked.connect(self.add_project_files);history_layout.addWidget(add_project_button)
        find_projects_button=QPushButton('폴더에서 작업 찾기');find_projects_button.clicked.connect(self.find_projects);history_layout.addWidget(find_projects_button)
        self.history_dock.setWidget(history_body);self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,self.history_dock)
        self.resizeDocks([self.history_dock],[290],Qt.Orientation.Horizontal)
        history_toggle=QPushButton('저장한 작업');history_toggle.setCheckable(True);history_toggle.setChecked(True)
        history_toggle.toggled.connect(self.history_dock.setVisible);self.history_dock.visibilityChanged.connect(history_toggle.setChecked)
        top.addWidget(history_toggle);self.history_toggle=history_toggle
        top.addStretch()
        self.export_controls=QWidget();export_controls=QHBoxLayout(self.export_controls);export_controls.setContentsMargins(0,0,0,0);export_controls.setSpacing(4);export_controls.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.export_controls.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Preferred)
        folder_button=QPushButton('저장 위치 변경');folder_button.clicked.connect(self.choose_export_folder);top.addWidget(folder_button)
        self.export_folder_label=QLabel(self.export_folder or '저장 위치: 최초 내보내기 때 선택');self.export_folder_label.setToolTip(self.export_folder)
        self.export_folder_label.setMaximumWidth(180);self.export_folder_label.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred);top.addWidget(self.export_folder_label)
        top.setStretchFactor(self.export_folder_label,1)
        export_controls.addWidget(QLabel('폴더 이름'))
        self.export_name=QLineEdit('a');self.export_name.setMinimumWidth(90);self.export_name.setMaximumWidth(150);export_controls.addWidget(self.export_name)
        self.export_name.textEdited.connect(lambda:self.mark_export_name_changed())
        self.output_checks={}
        for key,label in [('cen','처리본'),('uncen','원본용'),('main','메인용'),('banner','배너')]:
            check=QCheckBox(label);check.setToolTip('모자이크를 제외한 편집 적용 · 원본 확장자 유지 · 메타데이터 제거' if key=='uncen' else label);check.setChecked(self.settings.value('export/'+key,key!='banner',type=bool))
            check.toggled.connect(lambda value,k=key:self.settings.setValue('export/'+k,value))
            self.output_checks[key]=check;export_controls.addWidget(check)
        self.auto_mega=QCheckBox('MEGA 자동 공유');self.auto_mega.setChecked(self.settings.value('mega/autoShare',True,type=bool));self.auto_mega.setToolTip('원본용 내보내기 성공 후 암호 ZIP · MEGA 업로드 · 링크 TXT까지 자동 진행')
        self.auto_mega.toggled.connect(lambda value:self.settings.setValue('mega/autoShare',value));export_controls.addWidget(self.auto_mega)
        self.format=QComboBox(); self.format.addItems(['PNG','WEBP','JPEG']); export_controls.addWidget(self.format)
        self.export_button=QPushButton('내보내기');self.export_button.setObjectName('primaryButton'); self.export_button.clicked.connect(self.export); export_controls.addWidget(self.export_button)
        self.mega_button=QToolButton();self.mega_button.setText('MEGA로 공유');self.mega_button.setToolTip('이미 내보낸 원본용 폴더를 암호화 ZIP으로 압축 → 업로드 → 링크 TXT 생성')
        self.mega_button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup);self.mega_button.clicked.connect(self.share_uncensored)
        mega_menu=QMenu(self.mega_button);mega_menu.addAction('MEGA 연결 설정',self.mega_settings);mega_menu.addAction('실패한 업로드 재시도',self.retry_mega_share);self.mega_button.setMenu(mega_menu);export_controls.addWidget(self.mega_button)
        self.mode_controls=QWidget();mode_bar=QHBoxLayout(self.mode_controls);mode_bar.setContentsMargins(0,0,0,0);mode_bar.setSpacing(4)
        self.cut_mode_button=QPushButton('컷 편집 모드');self.cut_mode_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cut_mode_button.clicked.connect(self.toggle_cut_mode);mode_bar.addWidget(self.cut_mode_button)
        self.crop_mode_button=QPushButton('사진 자르기');self.crop_mode_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.crop_mode_button.clicked.connect(self.toggle_crop_mode);mode_bar.addWidget(self.crop_mode_button)
        rename_button=QPushButton('작업 이름 변경');rename_button.setFocusPolicy(Qt.FocusPolicy.NoFocus);rename_button.clicked.connect(self.rename_project);mode_bar.addWidget(rename_button)
        banner_button=QPushButton('배너 영역 선택');banner_button.clicked.connect(self.choose_banner);mode_bar.addWidget(banner_button)
        self.tool_controls=QWidget();mode_bar.addWidget(self.tool_controls,1)
        self.header_grid.addWidget(self.mode_controls,1,0);self.header_grid.addWidget(self.export_controls,1,1)
        self.editor_stack=QStackedWidget();layout.addWidget(self.editor_stack,1)
        self.splitter=QSplitter(Qt.Orientation.Horizontal); splitter=self.splitter
        splitter.setHandleWidth(5); splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet('QSplitter::handle:horizontal {background:#c2cbd6;border:0;} QSplitter::handle:horizontal:hover {background:#2788e8;}')
        self.editor_stack.addWidget(splitter)
        left=QWidget(); ll=QVBoxLayout(left)
        thumbnail_header=QHBoxLayout();ll.addLayout(thumbnail_header)
        thumbnail_header.addWidget(QLabel('드래그로 순서 변경 · Delete로 제외'))
        self.main_only=QCheckBox('메인만 보기');self.main_only.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.main_only.toggled.connect(self.apply_main_filter);thumbnail_header.addWidget(self.main_only)
        thumbnail_header.addStretch();self.selection_count=QLabel('선택 0장');thumbnail_header.addWidget(self.selection_count)
        self.list=ImageList();self.list.setObjectName('thumbnailList'); ll.addWidget(self.list); splitter.addWidget(left)
        self.list.itemSelectionChanged.connect(self.update_selection_count)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.thumbnail_context_menu)
        left.setMinimumWidth(180)
        right=QWidget(); right.setMinimumWidth(460); rl=QVBoxLayout(right)
        rl.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.title=QLabel('그림을 선택하세요');self.title.setObjectName('imageTitle'); rl.addWidget(self.title)
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
        brush_tools=QHBoxLayout(self.tool_controls);brush_tools.setContentsMargins(0,0,0,0)
        brush_tools.addWidget(QLabel('도구'))
        self.tool=ToolPicker(); brush_tools.addWidget(self.tool)
        self.tool.currentIndexChanged.connect(self.change_tool)
        self.tool.activated.connect(lambda:self.list.setFocus(Qt.FocusReason.OtherFocusReason))
        brush_tools.addWidget(QLabel('브러시 크기'))
        self.brush_size=NumericControl(); self.brush_size.setRange(5,200); self.brush_size.setValue(50)
        self.brush_size.valueChanged.connect(self.change_brush_size)
        brush_tools.addWidget(self.brush_size)
        softness_tools=brush_tools
        softness_tools.addWidget(QLabel('도장 경계'))
        self.clone_softness=NumericControl();self.clone_softness.setRange(0,100);self.clone_softness.setValue(50)
        self.clone_softness.valueChanged.connect(lambda value:setattr(self.canvas,'clone_softness',value/100))
        softness_tools.addWidget(self.clone_softness)
        tools=QHBoxLayout(); bottom_layout.addLayout(tools)
        brush_tools.addWidget(QLabel('모자이크 강도'))
        self.strength=NumericControl();self.strength.setKeyboardTracking(False);self.strength.setRange(2,100);self.strength.setValue(20);brush_tools.addWidget(self.strength)
        brush_tools.addStretch()
        for control in (self.brush_size,self.clone_softness,self.strength):
            control.setToolTip('숫자 직접 입력 · 휠로 1씩 조절 · Enter로 그림 목록에 복귀')
            control.lineEdit().returnPressed.connect(lambda:self.list.setFocus(Qt.FocusReason.OtherFocusReason))
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
        for key,fn in [('Delete',self.remove_selected),('Ctrl+S',self.save_project),('Ctrl+Shift+S',self.save_project_as),('Ctrl+O',self.load_project),('Right',lambda:self.navigate(1)),('Left',lambda:self.navigate(-1))]:
            action=QAction(self); action.setShortcut(QKeySequence(key)); action.triggered.connect(fn); self.addAction(action)
            if key in ('Delete','Right','Left'):self.navigation_actions.append(action)
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
        self.header.installEventFilter(self);self.adjust_header()
        saved_geometry=self.settings.value('layout/windowGeometry')
        if saved_geometry is not None:self.restoreGeometry(saved_geometry)
        self._last_window_geometry=self.saveGeometry();self._placement_ready=True
    def remember_window_geometry(self):
        if not self._placement_ready or self._restoring_placement or not self.isVisible() or self.isMinimized():return
        self._last_window_geometry=self.saveGeometry()
    def moveEvent(self,event):
        super().moveEvent(event);self.remember_window_geometry()
    def resizeEvent(self,event):
        super().resizeEvent(event);self.remember_window_geometry()
    def changeEvent(self,event):
        if event.type()==QEvent.Type.WindowStateChange and self._placement_ready:
            if self.isMinimized():
                # Ignore the minimized native window coordinates; retain its monitor.
                self._minimized_geometry=self._last_window_geometry
            elif event.oldState() & Qt.WindowState.WindowMinimized:
                self._restoring_placement=True
                QTimer.singleShot(0,self.restore_minimized_geometry)
        super().changeEvent(event)
    def restore_minimized_geometry(self):
        try:
            if self._minimized_geometry is not None and not self.isMinimized():
                self.restoreGeometry(self._minimized_geometry)
                self._minimized_geometry=None
        finally:self._restoring_placement=False
        self.remember_window_geometry()

    def eventFilter(self,watched,event):
        if watched is self.header and event.type()==QEvent.Type.Resize:self.adjust_header()
        return super().eventFilter(watched,event)
    def adjust_header(self):
        minimum=self.mode_controls.minimumSizeHint().width()+self.export_controls.minimumSizeHint().width()+self.header_grid.horizontalSpacing()
        stacked=self.header.width()<minimum
        if stacked==self.header_stacked:return
        self.header_stacked=stacked
        self.header_grid.removeWidget(self.mode_controls);self.header_grid.removeWidget(self.export_controls)
        if stacked:
            self.header_grid.addWidget(self.mode_controls,1,0,1,2);self.header_grid.addWidget(self.export_controls,2,0,1,2)
        else:
            self.header_grid.addWidget(self.mode_controls,1,0);self.header_grid.addWidget(self.export_controls,1,1)
    def change_tool(self,index):
        name=['box','brush','clone'][index]
        self.canvas.tool=name;self.settings.setValue('tools/selected',index)
        value=self.tool_sizes[name]
        self.brush_size.blockSignals(True);self.brush_size.setValue(value);self.brush_size.blockSignals(False)
        self.canvas.brush_radius=value/2000;self.canvas.update()
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
        self.history_summary.setText(f'저장한 작업 {len(self.recent_projects)}개 · 이름순')
        self.history_list.clear()
        for path in sorted(self.recent_projects,key=lambda value:(Path(value).name.removesuffix('.photo.json').casefold(),value.casefold())):
            file=Path(path);name=file.name.removesuffix('.photo.json')
            try:modified=datetime.fromtimestamp(file.stat().st_mtime).strftime('%Y-%m-%d %H:%M')
            except OSError:modified='파일 없음'
            item=QListWidgetItem(f'{name}  ·  {modified}')
            item.setSizeHint(QSize(0,34))
            item.setData(Qt.ItemDataRole.UserRole,path);item.setToolTip(f'{name}\n마지막 작업: {modified} (마지막 저장 기준)\n{path}');self.history_list.addItem(item)
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
        if self.crop_editor is not None:self.undo_button.setEnabled(False);self.redo_button.setEnabled(False);return
        if self.cut_editor is not None:
            self.undo_button.setEnabled(bool(self.cut_editor.history));self.redo_button.setEnabled(bool(self.cut_editor.redo_history));return
        self.undo_button.setEnabled(bool(self.history));self.redo_button.setEnabled(bool(self.redo_stack))
        self.undo_button.setToolTip('Ctrl+Z');self.redo_button.setToolTip('Ctrl+Y 또는 Ctrl+Shift+Z')
    def snapshot(self,label='작업 변경'):
        self.history.append(self.capture_state())
        self.history=self.history[-HISTORY_LIMIT:];self.history_labels.append(label);self.history_labels=self.history_labels[-HISTORY_LIMIT:]
        self.redo_stack.clear();self.update_history_controls();self.dirty=True
    def undo(self):
        if self.crop_editor is not None:return
        if self.cut_editor is not None:self.cut_editor.undo();return
        if not self.history:return
        label=self.history_labels.pop() if self.history_labels else '작업 변경'
        self.redo_stack.append((self.capture_state(),label))
        self.restore_state(self.history.pop());self.update_history_controls()
        self.status.setText('실행 취소: '+label)
    def redo(self):
        if self.crop_editor is not None:return
        if self.cut_editor is not None:self.cut_editor.redo();return
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
        visible=self.visible_rows()
        if visible:self.list.setCurrentRow(visible[0])
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
        if self.crop_editor is not None:self.finish_crop_mode(True)
        if self.cut_editor is not None:self.finish_cut_mode(True)
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
            if self.list.currentRow()<0 and self.visible_rows():self.list.setCurrentRow(self.visible_rows()[0])
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
            item.setText(f'{i+1:03d}  '+Path(entry['path']).name+('  [도장]' if entry.get('clones') else '')+('  [컷]' if entry.get('composition') else '')+('  [자름]' if entry.get('crop_source') else ''))
            regions=all_regions(entry);item.setData(MOSAIC_ROLE,bool(regions))
            item.setData(MAIN_ROLE,bool(entry.get('main_selected',False)))
            item.setToolTip(entry['path']+(f'\n모자이크 적용 · {len(regions)}개 영역' if regions else '\n모자이크 없음'))
        self.apply_main_filter()
    def visible_rows(self):
        return [row for row in range(self.list.count()) if not self.list.item(row).isHidden()]
    def apply_main_filter(self,*args):
        only=self.main_only.isChecked();old=self.list.currentItem();old_row=self.list.currentRow()
        blocked=self.list.blockSignals(True);changed=False
        try:
            for row in range(self.list.count()):
                item=self.list.item(row);entry=self.entries[item.data(Qt.ItemDataRole.UserRole)]
                hidden=only and not entry.get('main_selected',False)
                if item.isHidden()!=hidden:item.setHidden(hidden);changed=True
                if hidden:item.setSelected(False)
            visible=self.visible_rows()
            if visible and (self.list.currentItem() is None or self.list.currentItem().isHidden()):
                selected=[row for row in visible if self.list.item(row).isSelected()]
                target=selected[0] if selected else next((row for row in visible if row>=old_row),visible[-1])
                self.list.setCurrentRow(target,QItemSelectionModel.SelectionFlag.NoUpdate if selected else QItemSelectionModel.SelectionFlag.ClearAndSelect)
            elif not visible:self.list.setCurrentRow(-1);self.list.clearSelection()
            if changed:self.list.hover_row=-1;self.list.doItemsLayout()
        finally:self.list.blockSignals(blocked)
        current=self.list.currentItem()
        if current:self.list.selection_anchor=current.data(Qt.ItemDataRole.UserRole)
        if not blocked and current is not old:self.list.currentItemChanged.emit(current,old)
        self.update_selection_count();self.list.viewport().update()
        self.status.setText(f'총 {self.list.count()}장 · 모자이크 {sum(bool(e["regions"]) for e in self.entries.values())}장 · 메인 {sum(bool(e.get("main_selected")) for e in self.entries.values())}장')
    def order_changed(self):self.dirty=True; self.renumber()
    def remove_selected(self):
        if self.crop_editor is not None:self.finish_crop_mode(True)
        if self.cut_editor is not None:self.finish_cut_mode(True)
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
        visible=self.visible_rows()
        if not visible:return
        index=visible.index(self.list.currentRow()) if self.list.currentRow() in visible else 0
        row=visible[max(0,min(len(visible)-1,index+step))]
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
        if not composition and not entry.get('crop_source'):return image
        key=(id(entry),id(image),id(composition),id(entry.get('crop_source')))
        if key!=self.composition_cache_key:
            self.composition_cache_image=render_composition(crop_base(image,entry),composition);self.composition_cache_key=key
        return self.composition_cache_image
    def copy_for_cut(self):
        entry=self.current()
        if not entry:return
        try:
            raw=read_pixels(entry['path'])
            self.cut_clipboard=paired_asset(render_entry(raw,entry),render_entry(raw,entry,include_mosaic=False))
            self.status.setText('모자이크 포함 그림 복사 완료 · 대상 썸네일을 선택하고 컷 편집을 여세요.')
        except Exception as exc:QMessageBox.warning(self,'컷 복사 실패',str(exc))
    def apply_composition(self,composition):
        entry=self.current()
        if not entry or composition==entry.get('composition'):return
        validate_composition(composition);self.snapshot('컷 편집 / 합성')
        entry['composition']=copy.deepcopy(composition)
        self.clone_cache_key=None;self.composition_cache_key=None;self.render();self.renumber()
    def edit_cuts(self):
        if self.crop_editor is not None:self.finish_crop_mode(True)
        if self.cut_editor is not None:return self.cut_editor
        entry=self.current()
        if not entry:return
        from cut_editor import CutEditor
        try:
            editor=CutEditor(entry,self.ordered(),[self.list.item(i).icon() for i in range(self.list.count())],self.cut_clipboard,self,embedded=True)
            self.cut_editor=editor;self.editor_stack.addWidget(editor);self.editor_stack.setCurrentWidget(editor)
            self.tool_controls.setEnabled(False)
            editor.accepted.connect(lambda:self.finish_cut_mode(True));editor.rejected.connect(lambda:self.finish_cut_mode(False))
            editor.historyChanged.connect(self.update_history_controls)
            for action in self.navigation_actions:action.setEnabled(False)
            self.cut_mode_button.setText('모자이크 모드로');self.update_history_controls();editor.canvas.setFocus()
            return editor
        except Exception as exc:QMessageBox.warning(self,'컷 편집 실패',str(exc))
    def toggle_cut_mode(self):
        if self.cut_editor is not None:self.finish_cut_mode(True)
        else:self.edit_cuts()
    def sync_cut_editor(self):
        if self.crop_editor is not None:self.finish_crop_mode(True)
        editor=self.cut_editor
        if editor is None:return
        editor.finish_gesture()
        from composition import empty_composition
        if editor.composition!=(self.current().get('composition') or empty_composition()):self.apply_composition(editor.composition)
    def has_cut_changes(self):
        if self.cut_editor is None:return False
        from composition import empty_composition
        return self.cut_editor.composition!=(self.current().get('composition') or empty_composition())
    def finish_cut_mode(self,apply=True):
        editor=self.cut_editor
        if editor is None:return
        if apply:self.sync_cut_editor()
        self.cut_clipboard=editor.clipboard;self.cut_editor=None;editor.timer.stop()
        self.editor_stack.setCurrentWidget(self.splitter);self.editor_stack.removeWidget(editor);editor.deleteLater()
        for action in self.navigation_actions:action.setEnabled(True)
        self.cut_mode_button.setText('컷 편집 모드');self.update_history_controls();self.render();self.list.setFocus()
        self.tool_controls.setEnabled(True)
    def toggle_crop_mode(self):
        if self.crop_editor is not None:self.finish_crop_mode(True)
        else:self.start_crop_mode()
    def start_crop_mode(self):
        if self.crop_editor is not None:return self.crop_editor
        if self.cut_editor is not None:self.finish_cut_mode(True)
        entry=self.current()
        if not entry:return
        from crop_editor import CropEditor
        try:
            editor=CropEditor(entry,self);self.crop_editor=editor
            self.editor_stack.addWidget(editor);self.editor_stack.setCurrentWidget(editor)
            editor.accepted.connect(lambda:self.finish_crop_mode(True));editor.rejected.connect(lambda:self.finish_crop_mode(False))
            for action in self.navigation_actions:action.setEnabled(False)
            self.tool_controls.setEnabled(False);self.crop_mode_button.setText('자르기 적용');self.update_history_controls()
            return editor
        except Exception as exc:QMessageBox.warning(self,'사진 자르기 실패',str(exc))
    def apply_crop(self,rect,anchor=None,replace=False,mode='cover'):
        entry=self.current()
        if not entry or (rect==[0.,0.,1.,1.] and not replace):return
        if not replace and len(list(edit_layers(entry)))>=64:raise ValueError('연속 자르기는 최대 63회까지 지원합니다.')
        source=copy.deepcopy(entry['crop_source']['edits'] if replace else {key:entry[key] for key in ('regions','clones','composition','crop_source') if key in entry})
        pending={'regions':[],'clones':[],'crop_source':{'rect':list(rect),'edits':source,'mode':mode,'anchor':list(anchor or [.5,.5])}}
        validate_edits(pending);self.snapshot('사진 자르기 · 비율 유지 확대')
        entry.update(pending);entry.pop('composition',None)
        self.canvas.active=-1;self.clone_cache_key=None;self.composition_cache_key=None;self.original.setChecked(False)
        self.render();self.renumber();self.status.setText('원래 해상도에 맞춰 비율을 유지해 확대했습니다. Ctrl+Z로 취소')
    def finish_crop_mode(self,apply=True):
        editor=self.crop_editor
        if editor is None:return
        if apply and editor.has_changes():self.apply_crop(editor.rect(),editor.anchor,editor.replacing)
        editor.preview_timer.stop()
        self.crop_editor=None;self.editor_stack.setCurrentWidget(self.splitter);self.editor_stack.removeWidget(editor);editor.deleteLater()
        for action in self.navigation_actions:action.setEnabled(True)
        self.tool_controls.setEnabled(True);self.crop_mode_button.setText('사진 자르기');self.update_history_controls();self.render();self.list.setFocus()
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
        self.list.setFocus(Qt.FocusReason.OtherFocusReason)
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
                self.strength.blockSignals(True); self.strength.setValue(entry['regions'][event[1]]['strength']); self.strength.blockSignals(False)
        self.render(); self.renumber()
    def brush_bounds(self,region):
        image=self.cache.get(self.current()['path'])
        aspect=image.width/image.height if image else 1
        radius=region['radius']; points=region['points']
        region['rect']=[max(0,min(p[0] for p in points)-radius),max(0,min(p[1] for p in points)-radius*aspect),
                        min(1,max(p[0] for p in points)+radius),min(1,max(p[1] for p in points)+radius*aspect)]
    def strength_changed(self,value):
        entry=self.current();index=self.canvas.active
        if not entry or not 0<=index<len(entry['regions']):return
        if entry['regions'][index]['strength']==value:return
        self.snapshot('모자이크 강도 변경')
        entry['regions'][index]['strength']=value;self.dirty=True;self.render()
    def clear_mosaics(self,ids):
        targets=[self.entries[eid] for eid in set(ids) if eid in self.entries and all_regions(self.entries[eid])]
        if not targets:
            self.status.setText('지울 모자이크가 없습니다.');return
        self.snapshot(f'모자이크 초기화 · {len(targets)}장')
        for entry in targets:
            for layer in edit_layers(entry):layer['regions']=[]
        self.composition_cache_key=None;self.clone_cache_key=None
        self.canvas.active=-1;self.canvas.start=None;self.canvas.end=None;self.canvas.drawing_brush=False
        self.original.setChecked(False);self.render();self.renumber()
        self.status.setText(f'{len(targets)}장의 모자이크를 모두 지웠습니다. 도장 보정은 유지됩니다. Ctrl+Z로 복원')
    def batch_strength_dialog(self):
        ids=[item.data(Qt.ItemDataRole.UserRole) for item in self.list.selectedItems()]
        entries=[self.entries[eid] for eid in ids if all_regions(self.entries[eid])]
        count=sum(len(all_regions(entry)) for entry in entries)
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
        entries=[self.entries[eid] for eid in set(ids) if eid in self.entries and all_regions(self.entries[eid])]
        changed=[entry for entry in entries if any(r['strength']!=strength for r in all_regions(entry))]
        if not changed:
            self.status.setText('변경할 모자이크 강도가 없습니다.');return
        self.snapshot(f'모자이크 강도 일괄 변경 · {len(changed)}장')
        for entry in changed:
            for region in all_regions(entry):region['strength']=strength
        self.composition_cache_key=None;self.clone_cache_key=None
        # Updating the slider here must not create a separate edit or history entry.
        self.strength.blockSignals(True);self.strength.setValue(strength);self.strength.blockSignals(False)
        self.original.setChecked(False);self.render();self.renumber()
        self.status.setText(f'{len(changed)}장 · {sum(len(all_regions(e)) for e in changed)}개 영역 강도를 {strength}로 변경했습니다. Ctrl+Z로 일괄 취소')
    def remove_region(self):
        entry=self.current(); i=self.canvas.active
        if entry and 0<=i<len(entry['regions']):
            self.snapshot('모자이크 영역 삭제'); entry['regions'].pop(i); self.canvas.active=-1; self.render(); self.renumber()
    def save_project(self):
        if self.project:return self.write_project(self.project)
        return self.save_project_as()
    def rename_project(self):
        current=Path(self.project).name.removesuffix('.photo.json') if self.project else self.pending_project_name
        name,accepted=QInputDialog.getText(self,'작업 이름 변경','새 작업 이름:',text=current)
        if not accepted:return False
        name=name.strip()
        if name.lower().endswith('.photo.json'):name=name[:-11]
        reserved={'CON','PRN','AUX','NUL'}|{f'{kind}{i}' for kind in ('COM','LPT') for i in range(1,10)}
        if not name or name.endswith(('.', ' ')) or any(c in '<>:"/\\|?*' or ord(c)<32 for c in name) or name.split('.')[0].upper() in reserved:
            QMessageBox.warning(self,'이름 변경 실패','파일 이름에 사용할 수 없는 이름입니다.');return False
        if not self.project:
            self.pending_project_name=name;self.dirty=True;self.status.setText(f'새 작업 이름: {name} · 처음 저장할 때 위치를 선택하세요.');return True
        source=Path(self.project);target=source.with_name(name+'.photo.json')
        if str(source)==str(target):return True
        try:
            if target.exists() and not target.samefile(source):raise ValueError('같은 이름의 작업 파일이 이미 있습니다.')
            if not self.write_project(str(source)):return False
            source.rename(target)
            self.project=str(target.resolve());self.recent_projects=[p for p in self.recent_projects if p!=str(source)]
            self.remember_project(self.project);self.settings.setValue('session/lastProject',self.project);self.settings.sync()
            self.status.setText(f'작업 이름 변경 완료: {name}');return True
        except Exception as exc:
            QMessageBox.warning(self,'이름 변경 실패',str(exc));return False
    def mark_export_name_changed(self):
        self.dirty=True
    def new_project(self):
        if self.busy:
            QMessageBox.information(self,'내보내기 중','내보내기가 끝난 후 새 작업을 시작하세요.');return False
        if not self.confirm_discard():return False
        self.finish_crop_mode(False)
        self.finish_cut_mode(False)
        self.clone_timer.stop();self.clone_live=None;self.clone_live_entry=None
        self.clone_cache_key=None;self.composition_cache_key=None;self.cut_clipboard=None
        self.populate([]);self.history=[];self.history_labels=[];self.redo_stack=[];self.snapshot_cache={}
        self.project=None;self.dirty=False;self.update_history_controls();self.refresh_recent_projects()
        self.export_name.setText('a')
        self.pending_project_name='작업'
        self.settings.setValue('session/lastProject','');self.settings.remove('session/lastView');self.settings.sync()
        self.status.setText('새 작업 · 그림을 추가하세요.');return True
    def restore_last_project(self):
        # Upgrade from previous releases using the most recently opened/saved file.
        path=self.settings.value('session/lastProject','') if self.settings.contains('session/lastProject') else (self.recent_projects[0] if self.recent_projects else '')
        if not path:return False
        if not Path(path).is_file():
            self.status.setText('이전 작업 파일을 찾을 수 없습니다. 작업 열기로 위치를 지정하세요.');return False
        saved_view=self.settings.value('session/lastView','')
        if not self.open_project(path):return False
        if saved_view:
            try:
                view=json.loads(saved_view)
                if view.get('path')==self.project:self.restore_project_view(view)
            except (ValueError,TypeError,AttributeError):pass
        return True
    def restore_project_view(self,view):
        if not isinstance(view,dict):return
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole)==view.get('current_id'):
                if self.list.item(row).isHidden():break
                self.list.setCurrentRow(row,QItemSelectionModel.SelectionFlag.ClearAndSelect)
                self.list.scrollToItem(self.list.item(row));break
        self.list.doItemsLayout()
        if isinstance(view.get('scroll'),int):self.list.verticalScrollBar().setValue(view['scroll'])
    def save_project_as(self):
        path,_=QFileDialog.getSaveFileName(self,'다른 이름으로 작업 저장',self.project or self.pending_project_name+'.photo.json','Photo project (*.photo.json)')
        if path and not path.lower().endswith('.photo.json'):path+='.photo.json'
        return self.write_project(path)
    def write_project(self,path):
        if not path:return False
        self.sync_cut_editor()
        try:
            entry=self.current()
            view={'current_id':entry['id'] if entry else None,'scroll':self.list.verticalScrollBar().value()}
            temp=Path(path+'.tmp'); temp.write_text(json.dumps({'version':1,'images':self.ordered(),'view':view,'export':{'name':self.export_name.text()}},ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)
            self.project=str(Path(path).resolve()); self.dirty=False;self.remember_project(self.project)
            self.settings.setValue('session/lastProject',self.project);self.settings.remove('session/lastView');self.settings.sync()
            self.status.setText('작업 저장 완료');return True
        except Exception as exc:
            QMessageBox.warning(self,'저장 실패',str(exc));return False
    def confirm_discard(self):
        if not self.dirty and not self.has_cut_changes() and not (self.crop_editor and self.crop_editor.has_changes()):return True
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
            export_settings=data.get('export',{})
            if not isinstance(export_settings,dict) or not isinstance(export_settings.get('name','a'),str):raise ValueError('잘못된 출력 폴더 이름')
            for e in entries:
                if not isinstance(e.get('main_selected',False),bool):raise ValueError('잘못된 메인 선택 상태')
                if not isinstance(e['path'],str) or not isinstance(e['regions'],list):raise ValueError('잘못된 작업 파일')
                validate_edits(e)
            self.finish_crop_mode(False)
            self.finish_cut_mode(False)
            self.populate(entries); self.history=[]; self.history_labels=[]; self.redo_stack=[];self.snapshot_cache={};self.update_history_controls(); self.project=str(Path(path).resolve()); self.dirty=False
            self.restore_project_view(data.get('view',{}))
            self.export_name.setText(export_settings.get('name','a'))
            self.settings.setValue('session/lastProject',self.project);self.settings.remove('session/lastView');self.settings.sync()
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
            f'{path_text}\n위에 표시한 출력 폴더/파일만 삭제하고 새로 내보낼까요?\n체크하지 않은 출력 폴더와 그 밖의 파일은 유지됩니다.',buttons.Yes|buttons.No,self)
        box.button(buttons.Yes).setText('예');box.button(buttons.No).setText('아니오')
        box.setDefaultButton(buttons.No);box.setEscapeButton(buttons.No)
        return box.exec()==buttons.Yes
    def export(self):
        self.sync_cut_editor()
        if not self.entries or self.busy:return
        outputs={key:check.isChecked() for key,check in self.output_checks.items()}
        if not any(outputs.values()):
            self.status.setText('내보낼 항목을 하나 이상 체크하세요.');return
        if outputs['banner'] and not any(e.get('banner_rect') for e in self.entries.values()):
            QMessageBox.information(self,'배너 영역 필요','그림을 선택하고 배너 영역 선택에서 출력할 부분을 지정하세요.');return
        if outputs['main'] and not outputs['cen'] and not outputs['uncen'] and not outputs['banner'] and not any(e.get('main_selected') for e in self.entries.values()):
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
        self.export_mega_client=None
        if outputs['uncen'] and self.auto_mega.isChecked():
            self.export_mega_client=self.mega_client_path()
            if not self.export_mega_client:
                self.status.setText('MEGA 연결 설정을 완료한 뒤 다시 내보내거나 자동 공유를 해제하세요.');return
        try:
            destination=prepare_output(folder,stem,[entry['path'] for entry in self.entries.values()],self.confirm_output_replacement,outputs)
            if destination is None:
                self.status.setText('내보내기를 취소했습니다. 기존 파일은 유지됩니다.');return
        except (OSError,ValueError) as exc:
            QMessageBox.warning(self,'출력 폴더 준비 실패',str(exc));return
        entries=copy.deepcopy(self.ordered()); fmt=self.format.currentText(); ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
        self.busy=True; self.export_button.setEnabled(False);self.mega_button.setEnabled(False); self.progress.setRange(0,len(entries)); self.progress.setValue(0); self.progress.show(); self.errors=[]; self.exported_main=0;self.exported_files=0;self.exported_banner=False
        self.export_next(entries,0,destination,fmt,ext,stem,outputs)
    def export_next(self,entries,index,destination,fmt,ext,stem,outputs):
        if index==len(entries):
            if outputs.get('banner') and not self.exported_banner:
                self.exported_banner=True
                banner_entry=next(entry for entry in entries if entry.get('banner_rect'))
                def banner_complete(result):
                    if result[0]:self.exported_files+=1
                    else:self.errors.append('배너: '+str(result[1]))
                    self.export_next(entries,index,destination,fmt,ext,stem,outputs)
                self.run_job(self.export_pool,lambda:export_banner(banner_entry,Path(destination)/(stem+'_banner.png'),len(entries)),banner_complete);return
            self.busy=False; self.export_button.setEnabled(True);self.mega_button.setEnabled(True); self.progress.hide()
            message=f'{self.exported_files}개 파일 저장 완료\n{destination}'
            if outputs['cen']:message+=f'\n{stem}_cen: 모자이크 처리본'
            if outputs['uncen']:message+=f'\n{stem}_uncen: 원본용 · 편집 적용 / 모자이크 제외 / 메타데이터 제거'
            if outputs.get('banner'):message+=f'\n{stem}_banner.png: 선택 영역 배너'
            if self.exported_main:message+=f'\n{stem}_main: 메인 게시용 {self.exported_main}장'
            message+='\n출력 파일 메타데이터 제거 검증 완료'
            if self.errors:message+='\n\n실패:\n'+'\n'.join(self.errors[:10])
            if not self.errors and outputs['uncen'] and getattr(self,'export_mega_client',None):
                self.start_mega_share(self.export_mega_client,Path(destination)/(stem+'_uncen'),stem,export_message=message);return
            if self.errors and getattr(self,'export_mega_client',None):message+='\n파일 출력에 실패하여 MEGA 자동 공유는 실행하지 않았습니다.'
            QMessageBox.information(self,'내보내기 결과',message); return
        def complete(result):
            if not result[0]:self.errors.append(Path(entries[index]['path']).name+': '+result[1])
            else:
                self.exported_files+=len(result[1])
                if outputs['main'] and entries[index].get('main_selected',False):self.exported_main+=1
            self.progress.setValue(index+1); self.export_next(entries,index+1,destination,fmt,ext,stem,outputs)
        self.run_job(self.export_pool,lambda:export_pair(entries[index],index+1,destination,fmt,stem,outputs,self.exported_main+1),complete)
    def choose_banner(self):
        self.sync_cut_editor()
        entry=self.current()
        if not entry:return
        from banner_editor import BannerEditor
        try:
            editor=BannerEditor(entry,self,total_count=len(self.entries))
            if editor.exec():self.set_banner(entry['id'],editor.selection(),editor.text_options())
        except Exception as exc:QMessageBox.warning(self,'배너 선택 실패',str(exc))
    def set_banner(self,identifier,rect,text_options=None):
        probe=dict(self.entries[identifier],banner_rect=list(rect))
        if text_options is not None:probe['banner_text']=copy.deepcopy(text_options)
        validate_edits(probe)
        self.snapshot('배너 영역 지정')
        for entry in self.entries.values():
            if entry['id']!=identifier:entry.pop('banner_text',None)
            entry.pop('banner_rect',None)
        self.entries[identifier]['banner_rect']=list(rect)
        if text_options is not None:self.entries[identifier]['banner_text']=copy.deepcopy(text_options)
        self.output_checks['banner'].setChecked(True)
        self.status.setText('배너 영역 지정 완료 · 내보내기에서 '+self.export_name.text()+'_banner.png로 저장됩니다.')
    def mega_settings(self):
        from mega_dialog import MegaSettings
        MegaSettings(self.settings,self).exec()
    def mega_client_path(self):
        client=find_client(str(self.settings.value('mega/client','')))
        if not client:
            self.mega_settings();client=find_client(str(self.settings.value('mega/client','')))
        return client
    def share_uncensored(self):
        if self.busy:return
        stem=self.export_name.text().strip()
        if not stem or stem in ('.','..') or any(c in stem for c in '<>:"/\\|?*'):
            QMessageBox.warning(self,'출력 이름','올바른 출력 폴더 이름을 입력하세요.');return
        source=Path(self.export_folder)/stem/(stem+'_uncen')
        if not source.is_dir():
            folder=QFileDialog.getExistingDirectory(self,'이미 내보낸 원본용(_uncen) 폴더 선택',self.export_folder)
            if not folder:return
            source=Path(folder);stem=source.name.removesuffix('_uncen')
        client=self.mega_client_path()
        if client:self.start_mega_share(client,source,stem)
    def retry_mega_share(self):
        if self.busy:return
        path,_=QFileDialog.getOpenFileName(self,'업로드 재시도 파일 선택',self.export_folder,'Photo upload (*.upload.json)')
        if not path:return
        client=self.mega_client_path()
        if client:self.start_mega_share(client,state_path=path)
    def start_mega_share(self,client_path,source=None,stem=None,state_path=None,export_message=None):
        if self.busy:return
        self.busy=True;self.export_button.setEnabled(False);self.mega_button.setEnabled(False)
        self.progress.setRange(0,0);self.progress.show();self.status.setText('암호 압축 · MEGA 업로드 · 공유 링크 생성 중…')
        def work():
            client=MegaClient(client_path);client.check_login()
            path=state_path or create_package(source,stem)
            try:return upload_package(path,client)
            except Exception as exc:raise RuntimeError(f'{exc}\n재시도 파일: {path}\n메뉴의 실패한 업로드 재시도를 사용하세요.') from exc
        def complete(result):
            self.busy=False;self.export_button.setEnabled(True);self.mega_button.setEnabled(True);self.progress.hide()
            if result[0]:
                self.status.setText(f'MEGA 업로드와 TXT 저장 완료: {result[1]}')
                QMessageBox.information(self,'내보내기 및 MEGA 공유 완료' if export_message else 'MEGA 공유 완료',(export_message+'\n\n' if export_message else '')+f'링크와 압축 비밀번호를 저장했습니다.\n{result[1]}')
            else:
                self.status.setText('MEGA 공유 실패 · ZIP은 유지되며 재시도할 수 있습니다.')
                QMessageBox.warning(self,'MEGA 공유 실패',('이미지 내보내기는 완료됐지만 MEGA 공유에 실패했습니다.\n' if export_message else '')+str(result[1]))
        self.run_job(self.export_pool,work,complete)
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'작업 처리 중','내보내기 또는 MEGA 공유가 끝난 후 종료하세요.'); event.ignore(); return
        if not self.confirm_discard():event.ignore(); return
        if self.project:
            entry=self.current()
            self.settings.setValue('session/lastProject',self.project)
            self.settings.setValue('session/lastView',json.dumps({'path':self.project,'current_id':entry['id'] if entry else None,'scroll':self.list.verticalScrollBar().value()}))
        geometry=self._last_window_geometry if self.isMinimized() else self.saveGeometry()
        if geometry is not None:self.settings.setValue('layout/windowGeometry',geometry)
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
    apply_theme(app)
    window=Window(); window.show()
    if '--smoke-test' in sys.argv:
        assert not app.windowIcon().isNull() and not window.windowIcon().isNull()
        assert all(isinstance(control,QSpinBox) and control.parentWidget() is window.tool_controls for control in (window.brush_size,window.clone_softness,window.strength))
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
        cut_dialog.fill_original_resolution();cut_dialog.border.setValue(1);cut_dialog.apply()
        window.apply_composition(cut_dialog.composition)
        assert window.current()['composition']['cells'][0].get('asset')
        cut_result=render_entry(read_pixels(window.current()['path']),window.current())
        assert cut_result.size==(80,60) and cut_result.getpixel((10,30))[:3]==(0,128,0)
        assert cut_result.getpixel((0,30))[:3]==(0,0,0)
        inline=window.edit_cuts();assert not inline.isWindow() and window.editor_stack.currentWidget() is inline
        inline.canvas.active=len(inline.composition['cells'])-1;inline.set_mode('move');inline.nudge((1,0));inline.border.setValue(2)
        inline.final_preview.setChecked(True);assert not inline.canvas.show_guides
        window.finish_cut_mode(True);assert window.cut_editor is None
        smoke_order=[entry['path'] for entry in window.ordered()]
        window.set_main_for_ids([window.ordered()[i]['id'] for i in (0,3)],True)
        window.main_only.setChecked(True);assert window.visible_rows()==[0,3]
        window.main_only.setChecked(False);assert [entry['path'] for entry in window.ordered()]==smoke_order
        crop=window.start_crop_mode();assert not crop.isWindow()
        crop.trims['top'].setValue(5);crop.trims['bottom'].setValue(5);crop.result_check.setChecked(True);crop.reframe([.1,0.]);crop.accepted.emit()
        assert window.crop_editor is None and window.current().get('crop_source')
        assert window.current()['crop_source']['mode']=='cover' and window.current()['crop_source']['anchor'][0]<.5
        assert render_entry(read_pixels(window.current()['path']),window.current()).size==(80,60)
        for index,entry in enumerate(window.ordered()):
            export_image(entry,Path(smoke_folder.name)/f'output{index}.png','PNG')
        from banner_editor import BannerEditor
        banner_dialog=BannerEditor(window.current(),window);banner_dialog.reject()
        window.current()['banner_rect']=[.25,.25,.75,.75]
        from banner_text import DEFAULT_TEXT
        window.current()['banner_text']=dict(DEFAULT_TEXT)
        banner_smoke=Path(smoke_folder.name)/'smoke_banner.png';export_banner(window.current(),banner_smoke)
        with Image.open(banner_smoke) as banner_image:assert banner_image.size==(40,30) and not banner_image.getexif()
        from mega_dialog import MegaSettings
        mega_settings_dialog=MegaSettings(window.settings,window);mega_settings_dialog.reject()
        import pyzipper
        share_source=Path(smoke_folder.name)/'smoke_uncen';share_source.mkdir();(share_source/'001.png').write_bytes(b'smoke encrypted pixels')
        share_state=create_package(share_source,'smoke');share_data=json.loads(share_state.read_text(encoding='utf-8'))
        with pyzipper.AESZipFile(share_data['archive']) as archive:
            archive.setpassword(share_data['password'].encode('ascii'));assert archive.read('smoke_uncen/001.png')==b'smoke encrypted pixels'
        assert window.mega_button.text()=='MEGA로 공유'
        window.dirty=False
        QTimer.singleShot(1000,app.quit)
    else:QTimer.singleShot(0,window.restore_last_project)
    sys.exit(app.exec())
