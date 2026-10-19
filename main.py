import sys, json, uuid, copy, time
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QObject, QRunnable, QThreadPool, QTimer, QMimeData, QItemSelectionModel
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QAction, QKeySequence, QFontDatabase, QFont, QShortcut, QDrag
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QFileDialog,
    QMessageBox, QSlider, QComboBox, QProgressBar, QScrollArea, QStyledItemDelegate, QLayout, QInputDialog, QCheckBox)
from imaging import EXTENSIONS, read_pixels, render_regions, export_image, export_pair

def to_qimage(image):
    rgba = image.convert('RGBA')
    return QImage(rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4,
                  QImage.Format.Format_RGBA8888).copy()

class Signals(QObject):
    done = Signal(object)

class Job(QRunnable):
    def __init__(self, fn, callback):
        super().__init__(); self.fn = fn; self.signals = Signals(); self.signals.done.connect(callback)
    def run(self):
        try: result = (True, self.fn())
        except Exception as exc: result = (False, str(exc))
        self.signals.done.emit(result)

MOSAIC_ROLE = int(Qt.ItemDataRole.UserRole) + 1
MAIN_ROLE = int(Qt.ItemDataRole.UserRole) + 2

class ThumbnailDelegate(QStyledItemDelegate):
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
    dropped = Signal(list)
    reordered = Signal()
    reordering = Signal()
    def __init__(self):
        super().__init__()
        self.setItemDelegate(ThumbnailDelegate(self))
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(140, 110)); self.setGridSize(QSize(164, 150))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(True); self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(5); self.setAcceptDrops(True)
        self.setSelectionRectVisible(False)
        self.empty_press=False
        self.press_position=None; self.drag_ids=[]; self.dragging=False; self.drop_target=None
        self.setMouseTracking(True)
    def mousePressEvent(self,event):
        self.empty_press=not self.indexAt(event.position().toPoint()).isValid()
        self.press_position=None; self.dragging=False; self.drop_target=None
        if self.empty_press:
            if not event.modifiers():self.clearSelection()
            event.accept(); return
        super().mousePressEvent(event)
        if event.button()==Qt.MouseButton.LeftButton:
            self.press_position=event.position().toPoint()
            self.drag_ids=[self.item(row).data(Qt.ItemDataRole.UserRole) for row in range(self.count()) if self.item(row).isSelected()]
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
        if self.empty_press:event.accept(); return
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self,event):
        if self.dragging:
            target=self.target_at(event.position().toPoint()); ids=self.drag_ids[:]
            self.press_position=None; self.dragging=False; self.drop_target=None
            self.viewport().unsetCursor(); self.move_ids(ids,target); self.viewport().update()
            self.setState(QAbstractItemView.State.NoState)
            event.accept(); return
        self.press_position=None
        if self.empty_press:
            self.empty_press=False; event.accept(); return
        super().mouseReleaseEvent(event)
    def paintEvent(self,event):
        super().paintEvent(event)
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
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(self.MIME):event.acceptProposedAction()
        else:event.ignore()
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(self.MIME):event.acceptProposedAction()
        else:event.ignore()
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
        if event.mimeData().hasUrls():
            self.dropped.emit([url.toLocalFile() for url in event.mimeData().urls()]); event.acceptProposedAction()
        elif event.mimeData().hasFormat(self.MIME):
            try:ids=json.loads(bytes(event.mimeData().data(self.MIME)).decode('utf-8'))
            except (ValueError,UnicodeDecodeError):event.ignore(); return
            pos=event.position().toPoint(); index=self.indexAt(pos); target=index.row()
            if target<0:target=self.count()
            elif pos.x()>=self.visualRect(index).center().x():target+=1
            self.move_ids(ids,target); event.setDropAction(Qt.DropAction.MoveAction); event.accept()
        else:event.ignore()

class Canvas(QWidget):
    selected = Signal(object)
    def __init__(self):
        super().__init__(); self.setMinimumSize(320, 300)
        self.pixmap = None; self.regions = []; self.active = -1; self.start = None; self.end = None
        self.tool='box'; self.brush_radius=.025; self.stroke=[]; self.drawing_brush=False
        self.zoom = 1.0; self.target = QRectF()
    def normalized(self, point):
        return (max(0., min(1., (point.x()-self.target.x())/max(1,self.target.width()))),
                max(0., min(1., (point.y()-self.target.y())/max(1,self.target.height()))))
    def paintEvent(self, event):
        p = QPainter(self); p.fillRect(self.rect(), QColor('#14171d'))
        if not self.pixmap:
            p.setPen(QColor('#a4aec0')); p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, '그림을 드래그해서 추가하세요'); return
        size = self.pixmap.size(); scale = min(self.width()/size.width(), self.height()/size.height())
        w,h = size.width()*scale,size.height()*scale
        self.target = QRectF((self.width()-w)/2,(self.height()-h)/2,w,h)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(self.target, self.pixmap, QRectF(self.pixmap.rect()))
        if self.start is not None and self.end is not None:
            p.setPen(QPen(QColor('#ffffff'),2,Qt.PenStyle.DashLine)); p.drawRect(QRectF(self.start,self.end).normalized())
    def mousePressEvent(self,event):
        if self.pixmap and event.button()==Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            if self.tool=='brush':
                self.drawing_brush=True; self.stroke=[self.normalized(event.position())]
                self.selected.emit(('brush_start',{'points':self.stroke.copy(),'radius':self.brush_radius}))
            else:
                self.start=event.position(); self.end=self.start
    def mouseMoveEvent(self,event):
        if self.drawing_brush:
            self.stroke.append(self.normalized(event.position()))
            self.selected.emit(('brush_move',self.stroke.copy()))
            return
        if self.start is not None: self.end=event.position(); self.update()
    def mouseReleaseEvent(self,event):
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
        super().__init__(); self.setWindowTitle('Photo · 그림 정리와 모자이크 · 순서 드래그 수정 v0.2.8'); self.resize(1400,900)
        self.entries={}; self.cache=OrderedDict(); self.pending=set(); self.history=[]; self.dirty=False; self.project=None
        self.pool=QThreadPool(self); self.pool.setMaxThreadCount(4)
        self.preview_pool=QThreadPool(self); self.preview_pool.setMaxThreadCount(2)
        self.export_pool=QThreadPool(self); self.export_pool.setMaxThreadCount(1)
        self.jobs=set(); self.errors=[]; self.busy=False
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root)
        top=QHBoxLayout(); layout.addLayout(top)
        for label,fn in [('파일 추가',self.add_dialog),('폴더 추가',self.folder_dialog),('작업 열기',self.load_project),('작업 저장',self.save_project),('실행 취소',self.undo),('목록에서 제외',self.remove_selected)]:
            button=QPushButton(label); button.clicked.connect(fn); top.addWidget(button)
        top.addStretch(); self.format=QComboBox(); self.format.addItems(['PNG','WEBP','JPEG']); top.addWidget(self.format)
        self.export_button=QPushButton('순서대로 내보내기'); self.export_button.clicked.connect(self.export); top.addWidget(self.export_button)
        self.splitter=QSplitter(Qt.Orientation.Horizontal); splitter=self.splitter
        splitter.setHandleWidth(14); splitter.setChildrenCollapsible(False)
        splitter.setStyleSheet('QSplitter::handle:horizontal {background:#687c94; border:4px solid #dfe5ed; border-radius:5px;} QSplitter::handle:horizontal:hover {background:#2788e8;}')
        layout.addWidget(splitter,1)
        left=QWidget(); ll=QVBoxLayout(left); ll.addWidget(QLabel('썸네일 드래그로 순서 변경 · Delete로 제외'))
        self.list=ImageList(); ll.addWidget(self.list); splitter.addWidget(left)
        left.setMinimumWidth(180)
        right=QWidget(); right.setMinimumWidth(460); rl=QVBoxLayout(right)
        rl.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.title=QLabel('그림을 선택하세요'); rl.addWidget(self.title)
        self.main_check=QCheckBox('메인 게시용으로 선택 · 별도 폴더에도 저장')
        self.main_check.setEnabled(False); self.main_check.toggled.connect(self.toggle_main)
        rl.addWidget(self.main_check)
        self.canvas=Canvas(); rl.addWidget(self.canvas,1)
        brush_tools=QHBoxLayout(); rl.addLayout(brush_tools)
        brush_tools.addWidget(QLabel('도구'))
        self.tool=QComboBox(); self.tool.addItems(['박스','브러시']); brush_tools.addWidget(self.tool)
        self.tool.currentIndexChanged.connect(lambda index:setattr(self.canvas,'tool','brush' if index else 'box'))
        brush_tools.addWidget(QLabel('브러시 크기'))
        self.brush_size=QSlider(Qt.Orientation.Horizontal); self.brush_size.setRange(5,200); self.brush_size.setValue(50)
        self.brush_size.valueChanged.connect(lambda value:setattr(self.canvas,'brush_radius',value/2000))
        brush_tools.addWidget(self.brush_size)
        self.brush_value=QLabel('50'); brush_tools.addWidget(self.brush_value)
        self.brush_size.valueChanged.connect(lambda value:self.brush_value.setText(str(value)))
        tools=QHBoxLayout(); rl.addLayout(tools)
        tools.addWidget(QLabel('모자이크 강도'))
        self.strength=QSlider(Qt.Orientation.Horizontal); self.strength.setTracking(True); self.strength.setRange(2,100); self.strength.setValue(20); tools.addWidget(self.strength)
        self.value=QLabel('20'); tools.addWidget(self.value)
        delete_region=QPushButton('선택 영역 삭제'); tools.addWidget(delete_region); delete_region.clicked.connect(self.remove_region)
        self.original=QPushButton('원본 비교'); self.original.setCheckable(True); tools.addWidget(self.original); self.original.toggled.connect(self.render)
        batch_tools=QHBoxLayout(); rl.addLayout(batch_tools)
        self.batch_strength_button=QPushButton('선택 사진 강도 일괄 변경')
        self.batch_strength_button.clicked.connect(self.batch_strength_dialog); batch_tools.addWidget(self.batch_strength_button)
        batch_tools.addWidget(QLabel('Ctrl/Shift로 여러 장 선택 · Ctrl+A로 전체 선택')); batch_tools.addStretch()
        rl.addWidget(QLabel('박스: 드래그 / 영역 클릭 · 브러시: 문지르기 · Ctrl+Z: 취소 · ← / →: 이전 / 다음 그림'))
        splitter.addWidget(right); splitter.setSizes([580,820])
        splitter.handle(1).setCursor(Qt.CursorShape.SizeHorCursor)
        splitter.handle(1).setToolTip('좌우로 드래그해서 썸네일과 미리보기 너비 조절')
        self.progress=QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        self.status=QLabel('원본을 보존하며, 결과 파일에는 메타데이터를 저장하지 않습니다.'); layout.addWidget(self.status)
        self.list.dropped.connect(self.add_paths); self.list.currentItemChanged.connect(self.selection_changed)
        self.list.reordering.connect(self.snapshot); self.list.reordered.connect(self.order_changed); self.canvas.selected.connect(self.region_event)
        self.strength.valueChanged.connect(self.strength_changed)
        self.strength.sliderPressed.connect(self.begin_strength_change)
        self.strength.sliderMoved.connect(self.strength.setValue)
        self.strength.actionTriggered.connect(self.strength_action)
        for key,fn in [('Delete',self.remove_selected),('Ctrl+S',self.save_project),('Ctrl+O',self.load_project),('Right',lambda:self.navigate(1)),('Left',lambda:self.navigate(-1))]:
            action=QAction(self); action.setShortcut(QKeySequence(key)); action.triggered.connect(fn); self.addAction(action)
        self.undo_shortcut=QShortcut(QKeySequence.StandardKey.Undo,self)
        self.undo_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.undo_shortcut.activated.connect(self.undo)
        self.setAcceptDrops(True)
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
    def snapshot(self):
        entry=self.current()
        self.history.append((copy.deepcopy(self.ordered()),entry['id'] if entry else None,self.canvas.active))
        self.history=self.history[-30:]; self.dirty=True
    def undo(self):
        if not self.history: return
        state,current_id,active=self.history.pop()
        # Editing a region does not require reloading every thumbnail.
        if [e['id'] for e in state]==[e['id'] for e in self.ordered()]:
            self.entries={e['id']:e for e in state}
        else:
            self.populate(state)
        for row in range(self.list.count()):
            if self.list.item(row).data(Qt.ItemDataRole.UserRole)==current_id:
                self.list.setCurrentRow(row); break
        entry=self.current()
        self.canvas.active=min(active,len(entry['regions'])-1) if entry else -1
        if entry and self.canvas.active>=0:
            self.strength.blockSignals(True)
            self.strength.setValue(entry['regions'][self.canvas.active]['strength'])
            self.strength.blockSignals(False)
            self.value.setText(str(self.strength.value()))
        self.original.setChecked(False); self.render(); self.renumber(); self.dirty=True
    def populate(self,entries):
        self.list.clear(); self.entries={}
        for entry in entries: self.insert_entry(entry)
        self.renumber()
        if self.list.count(): self.list.setCurrentRow(0)
        else: self.canvas.pixmap=None; self.canvas.update()
    def insert_entry(self,entry):
        entry.setdefault('main_selected',False)
        self.entries[entry['id']]=entry
        item=QListWidgetItem(Path(entry['path']).name); item.setData(Qt.ItemDataRole.UserRole,entry['id']); item.setToolTip(entry['path']); self.list.addItem(item)
        path=entry['path']
        self.run_job(self.pool,lambda:self.load_thumb(path),lambda result,eid=entry['id']:self.thumb_ready(eid,result))
    @staticmethod
    def load_thumb(path):
        image=read_pixels(path); image.thumbnail((140,110)); return to_qimage(image)
    def thumb_ready(self,eid,result):
        if not result[0]:
            if eid in self.entries: self.status.setText('읽기 실패: '+self.entries[eid]['path'])
            return
        for i in range(self.list.count()):
            item=self.list.item(i)
            if item.data(Qt.ItemDataRole.UserRole)==eid: item.setIcon(QPixmap.fromImage(result[1])); break
    def add_dialog(self):
        files,_=QFileDialog.getOpenFileNames(self,'그림 추가','','Images (*.webp *.png *.jpg *.jpeg *.bmp *.tif *.tiff)'); self.add_paths(files)
    def folder_dialog(self):
        path=QFileDialog.getExistingDirectory(self,'그림 폴더'); self.add_paths([path] if path else [])
    def add_paths(self,paths):
        expanded=[]
        for path in paths:
            p=Path(path)
            expanded.extend(sorted(p.rglob('*')) if p.is_dir() else [p])
        known={e['path'] for e in self.entries.values()}
        paths=[str(p.resolve()) for p in expanded if p.is_file() and p.suffix.lower() in EXTENSIONS]
        paths=list(dict.fromkeys(p for p in paths if p not in known))
        if not paths:return
        self.snapshot()
        for path in paths:self.insert_entry({'id':uuid.uuid4().hex,'path':path,'regions':[]})
        self.renumber()
        if self.list.currentRow()<0:self.list.setCurrentRow(0)
    def renumber(self):
        for i in range(self.list.count()):
            item=self.list.item(i); entry=self.entries[item.data(Qt.ItemDataRole.UserRole)]
            item.setText(f'{i+1:03d}  '+Path(entry['path']).name)
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
        self.snapshot(); self.list.blockSignals(True)
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
    def navigate(self,step):self.list.setCurrentRow(max(0,min(self.list.count()-1,self.list.currentRow()+step)))
    def sync_main_check(self):
        entry=self.current()
        self.main_check.blockSignals(True)
        self.main_check.setEnabled(entry is not None)
        self.main_check.setChecked(bool(entry and entry.get('main_selected',False)))
        self.main_check.blockSignals(False)
    def toggle_main(self,checked):
        entry=self.current()
        if not entry or bool(entry.get('main_selected',False))==checked:return
        self.snapshot();entry['main_selected']=checked;self.renumber()
    def selection_changed(self,*args):
        self.sync_main_check()
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
    def render(self,*args):
        self.sync_main_check()
        entry=self.current()
        if not entry or entry['path'] not in self.cache:return
        image=self.cache[entry['path']]
        image=image if self.original.isChecked() else render_regions(image,entry['regions'])
        self.canvas.pixmap=QPixmap.fromImage(to_qimage(image))
        self.canvas.regions=[] if self.original.isChecked() else entry['regions']; self.canvas.update()
    def region_event(self,event):
        entry=self.current()
        if not entry or self.original.isChecked():return
        if event[0]=='brush_start':
            self.snapshot()
            region={'kind':'brush','points':event[1]['points'],'radius':event[1]['radius'],'strength':self.strength.value()}
            self.brush_bounds(region); entry['regions'].append(region); self.canvas.active=len(entry['regions'])-1
        elif event[0]=='brush_move':
            if not 0<=self.canvas.active<len(entry['regions']):return
            region=entry['regions'][self.canvas.active]
            region['points']=event[1]; self.brush_bounds(region)
        elif event[0]=='add':
            self.snapshot(); entry['regions'].append({'rect':event[1],'strength':self.strength.value()}); self.canvas.active=len(entry['regions'])-1
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
        entry=self.current()
        if entry and 0<=self.canvas.active<len(entry['regions']):self.snapshot()
    def strength_action(self,*args):
        if not self.strength.isSliderDown(): self.begin_strength_change()
    def strength_changed(self,value):
        self.value.setText(str(value)); entry=self.current(); i=self.canvas.active
        if entry and 0<=i<len(entry['regions']):entry['regions'][i]['strength']=value; self.dirty=True; self.render()
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
        self.snapshot()
        for entry in changed:
            for region in entry['regions']:region['strength']=strength
        # Updating the slider here must not create a separate edit or history entry.
        self.strength.blockSignals(True);self.strength.setValue(strength);self.strength.blockSignals(False)
        self.value.setText(str(strength));self.original.setChecked(False);self.render();self.renumber()
        self.status.setText(f'{len(changed)}장 · {sum(len(e["regions"]) for e in changed)}개 영역 강도를 {strength}로 변경했습니다. Ctrl+Z로 일괄 취소')
    def remove_region(self):
        entry=self.current(); i=self.canvas.active
        if entry and 0<=i<len(entry['regions']):
            self.snapshot(); entry['regions'].pop(i); self.canvas.active=-1; self.render(); self.renumber()
    def save_project(self):
        path,_=QFileDialog.getSaveFileName(self,'작업 저장',self.project or '작업.photo.json','Photo project (*.photo.json)')
        if not path:return
        try:
            temp=Path(path+'.tmp'); temp.write_text(json.dumps({'version':1,'images':self.ordered()},ensure_ascii=False,indent=2),encoding='utf-8'); temp.replace(path)
            self.project=path; self.dirty=False; self.status.setText('작업 저장 완료')
        except Exception as exc:QMessageBox.warning(self,'저장 실패',str(exc))
    def confirm_discard(self):
        return not self.dirty or QMessageBox.question(self,'저장하지 않은 작업','저장하지 않은 변경 사항이 있습니다. 계속할까요?',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes
    def load_project(self):
        if not self.confirm_discard():return
        path,_=QFileDialog.getOpenFileName(self,'작업 열기','','Photo project (*.photo.json)')
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8')); entries=data['images']
            if data.get('version')!=1:raise ValueError('지원하지 않는 작업 파일입니다.')
            for e in entries:
                if not isinstance(e.get('main_selected',False),bool):raise ValueError('잘못된 메인 선택 상태')
                if not isinstance(e['path'],str) or not isinstance(e['regions'],list):raise ValueError('잘못된 작업 파일')
                for r in e['regions']:
                    if len(r['rect'])!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in r['rect']) or not 2<=r['strength']<=100:raise ValueError('잘못된 모자이크 영역')
                    if r.get('kind')=='brush':
                        if not isinstance(r.get('points'),list) or not r['points'] or not 0<r.get('radius',0)<=.1:raise ValueError('잘못된 브러시 영역')
                        if not all(len(point)==2 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in point) for point in r['points']):raise ValueError('잘못된 브러시 좌표')
            self.populate(entries); self.history=[]; self.project=path; self.dirty=False
        except Exception as exc:QMessageBox.warning(self,'열기 실패',str(exc))
    def export(self):
        if not self.entries or self.busy:return
        folder=QFileDialog.getExistingDirectory(self,'결과를 저장할 상위 폴더')
        if not folder:return
        stem,accepted=QInputDialog.getText(self,'출력 폴더 이름','폴더 이름 (예: a → a/a_cen, a/a_uncen, a/a_main):',text='a')
        if not accepted:return
        stem=stem.strip()
        if not stem or stem in {'.','..'} or any(c in stem for c in '<>:"/\\|?*') or stem.endswith('.'):
            QMessageBox.warning(self,'폴더 이름','사용할 수 없는 폴더 이름입니다.');return
        reserved={'CON','PRN','AUX','NUL'}|{f'COM{i}' for i in range(1,10)}|{f'LPT{i}' for i in range(1,10)}
        if stem.split('.')[0].upper() in reserved or any(ord(c)<32 for c in stem):
            QMessageBox.warning(self,'폴더 이름','사용할 수 없는 폴더 이름입니다.');return
        destination=Path(folder)/stem
        try:destination.mkdir()
        except FileExistsError:
            QMessageBox.warning(self,'폴더가 이미 있습니다',f'{destination}\n다른 이름을 입력하거나 다른 저장 위치를 선택하세요.');return
        except OSError as exc:
            QMessageBox.warning(self,'폴더 생성 실패',str(exc));return
        entries=copy.deepcopy(self.ordered()); fmt=self.format.currentText(); ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
        self.busy=True; self.export_button.setEnabled(False); self.progress.setRange(0,len(entries)); self.progress.setValue(0); self.progress.show(); self.errors=[]; self.exported_main=0
        self.export_next(entries,0,destination,fmt,ext,stem)
    def export_next(self,entries,index,destination,fmt,ext,stem):
        if index==len(entries):
            self.busy=False; self.export_button.setEnabled(True); self.progress.hide()
            message=f'{len(entries)-len(self.errors)}쌍 저장 완료\n{destination}\n{stem}_cen: 모자이크 처리본\n{stem}_uncen: 원본 압축 데이터 유지 · 메타데이터만 제거\n양쪽 모두 메타데이터 제거 검증 완료'
            if self.exported_main:message+=f'\n{stem}_main: 메인 게시용 처리본 {self.exported_main}장'
            if self.errors:message+='\n\n실패:\n'+'\n'.join(self.errors[:10])
            QMessageBox.information(self,'내보내기 결과',message); return
        def complete(result):
            if not result[0]:self.errors.append(Path(entries[index]['path']).name+': '+result[1])
            elif entries[index].get('main_selected',False):self.exported_main+=1
            self.progress.setValue(index+1); self.export_next(entries,index+1,destination,fmt,ext,stem)
        self.run_job(self.export_pool,lambda:export_pair(entries[index],index+1,destination,fmt,stem),complete)
    def closeEvent(self,event):
        if self.busy:QMessageBox.information(self,'내보내기 중','내보내기가 끝난 후 종료하세요.'); event.ignore(); return
        if not self.confirm_discard():event.ignore(); return
        self.pool.waitForDone(); self.preview_pool.waitForDone(); event.accept()

if __name__=='__main__':
    app=QApplication(sys.argv); app.setStyle('Fusion')
    font_path=Path('C:/Windows/Fonts/malgun.ttf')
    if font_path.exists():
        font_id=QFontDatabase.addApplicationFont(str(font_path))
        families=QFontDatabase.applicationFontFamilies(font_id)
        if families: app.setFont(QFont(families[0], 10))
    app.setStyleSheet('QWidget {font-family: "Malgun Gothic"; font-size: 12px;} QPushButton {padding: 8px 12px;} QListWidget {background:#202630;color:#eef2f8;} QListWidget::item:selected {background:#355e89;}')
    window=Window(); window.show()
    if '--smoke-test' in sys.argv:
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
        for index,entry in enumerate(window.ordered()):
            export_image(entry,Path(smoke_folder.name)/f'output{index}.png','PNG')
        window.dirty=False
        QTimer.singleShot(1000,app.quit)
    sys.exit(app.exec())
