import sys, json, uuid, copy, time
from pathlib import Path
from collections import OrderedDict
from PySide6.QtCore import Qt, QSize, QRectF, Signal, QObject, QRunnable, QThreadPool, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QAction, QKeySequence, QFontDatabase, QFont
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QAbstractItemView, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSplitter, QFileDialog,
    QMessageBox, QSlider, QComboBox, QProgressBar, QScrollArea)
from imaging import EXTENSIONS, read_pixels, render_regions, export_image

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

class ImageList(QListWidget):
    dropped = Signal(list)
    reordered = Signal()
    reordering = Signal()
    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(140, 110)); self.setGridSize(QSize(164, 150))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSpacing(5); self.setAcceptDrops(True)
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragEnterEvent(event)
    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: super().dragMoveEvent(event)
    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.dropped.emit([url.toLocalFile() for url in event.mimeData().urls()]); event.acceptProposedAction()
        else:
            self.reordering.emit()
            target = self.indexAt(event.position().toPoint()).row()
            if target < 0: target = self.count()
            rows = sorted(self.row(item) for item in self.selectedItems())
            target -= sum(row < target for row in rows)
            items = [self.takeItem(row) for row in reversed(rows)][::-1]
            for offset, item in enumerate(items): self.insertItem(target+offset, item)
            if items: self.setCurrentItem(items[0])
            event.acceptProposedAction(); self.reordered.emit()

class Canvas(QWidget):
    selected = Signal(object)
    def __init__(self):
        super().__init__(); self.setMinimumSize(320, 300)
        self.pixmap = None; self.regions = []; self.active = -1; self.start = None; self.end = None
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
        for i,r in enumerate(self.regions):
            a,b,c,d = r['rect']; p.setPen(QPen(QColor('#ffcf66' if i==self.active else '#69b5ff'),2))
            p.drawRect(QRectF(self.target.x()+a*w,self.target.y()+b*h,(c-a)*w,(d-b)*h))
        if self.start is not None and self.end is not None:
            p.setPen(QPen(QColor('#ffffff'),2,Qt.PenStyle.DashLine)); p.drawRect(QRectF(self.start,self.end).normalized())
    def mousePressEvent(self,event):
        if self.pixmap and event.button()==Qt.MouseButton.LeftButton and self.target.contains(event.position()):
            self.start=event.position(); self.end=self.start
    def mouseMoveEvent(self,event):
        if self.start is not None: self.end=event.position(); self.update()
    def mouseReleaseEvent(self,event):
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
        super().__init__(); self.setWindowTitle('Photo · 그림 정리와 모자이크'); self.resize(1400,900)
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
        splitter=QSplitter(); layout.addWidget(splitter,1)
        left=QWidget(); ll=QVBoxLayout(left); ll.addWidget(QLabel('썸네일 드래그로 순서 변경 · Delete로 제외'))
        self.list=ImageList(); ll.addWidget(self.list); splitter.addWidget(left)
        right=QWidget(); rl=QVBoxLayout(right)
        self.title=QLabel('그림을 선택하세요'); rl.addWidget(self.title)
        self.canvas=Canvas(); rl.addWidget(self.canvas,1)
        tools=QHBoxLayout(); rl.addLayout(tools)
        tools.addWidget(QLabel('모자이크 강도'))
        self.strength=QSlider(Qt.Orientation.Horizontal); self.strength.setRange(2,100); self.strength.setValue(20); tools.addWidget(self.strength)
        self.value=QLabel('20'); tools.addWidget(self.value)
        delete_region=QPushButton('선택 영역 삭제'); tools.addWidget(delete_region); delete_region.clicked.connect(self.remove_region)
        self.original=QPushButton('원본 비교'); self.original.setCheckable(True); tools.addWidget(self.original); self.original.toggled.connect(self.render)
        rl.addWidget(QLabel('드래그: 모자이크 추가 · 영역 클릭: 강도 변경 · ← / →: 이전 / 다음 그림'))
        splitter.addWidget(right); splitter.setSizes([580,820])
        self.progress=QProgressBar(); self.progress.hide(); layout.addWidget(self.progress)
        self.status=QLabel('원본을 보존하며, 결과 파일에는 메타데이터를 저장하지 않습니다.'); layout.addWidget(self.status)
        self.list.dropped.connect(self.add_paths); self.list.currentItemChanged.connect(self.selection_changed)
        self.list.reordering.connect(self.snapshot); self.list.reordered.connect(self.order_changed); self.canvas.selected.connect(self.region_event)
        self.strength.valueChanged.connect(self.strength_changed)
        self.strength.sliderPressed.connect(self.snapshot)
        self.strength.actionTriggered.connect(self.strength_action)
        for key,fn in [('Delete',self.remove_selected),('Ctrl+Z',self.undo),('Ctrl+S',self.save_project),('Ctrl+O',self.load_project),('Right',lambda:self.navigate(1)),('Left',lambda:self.navigate(-1))]:
            action=QAction(self); action.setShortcut(QKeySequence(key)); action.triggered.connect(fn); self.addAction(action)
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
        self.history.append(copy.deepcopy(self.ordered())); self.history=self.history[-30:]; self.dirty=True
    def undo(self):
        if not self.history: return
        state=self.history.pop(); self.populate(state); self.dirty=True
    def populate(self,entries):
        self.list.clear(); self.entries={}
        for entry in entries: self.insert_entry(entry)
        self.renumber()
        if self.list.count(): self.list.setCurrentRow(0)
        else: self.canvas.pixmap=None; self.canvas.update()
    def insert_entry(self,entry):
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
            item.setText(f'{i+1:03d}  '+Path(entry['path']).name+('  ●' if entry['regions'] else ''))
        self.status.setText(f'총 {self.list.count()}장 · 모자이크 {sum(bool(e["regions"]) for e in self.entries.values())}장')
    def order_changed(self):self.dirty=True; self.renumber()
    def remove_selected(self):
        items=self.list.selectedItems()
        if not items:return
        self.snapshot()
        self.list.blockSignals(True)
        for item in items:
            self.entries.pop(item.data(Qt.ItemDataRole.UserRole),None); self.list.takeItem(self.list.row(item))
        self.list.blockSignals(False)
        self.renumber(); self.selection_changed()
    def navigate(self,step):self.list.setCurrentRow(max(0,min(self.list.count()-1,self.list.currentRow()+step)))
    def selection_changed(self,*args):
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
        entry=self.current()
        if not entry or entry['path'] not in self.cache:return
        image=self.cache[entry['path']]
        image=image if self.original.isChecked() else render_regions(image,entry['regions'])
        self.canvas.pixmap=QPixmap.fromImage(to_qimage(image))
        self.canvas.regions=[] if self.original.isChecked() else entry['regions']; self.canvas.update()
    def region_event(self,event):
        entry=self.current()
        if not entry or self.original.isChecked():return
        if event[0]=='add':
            self.snapshot(); entry['regions'].append({'rect':event[1],'strength':self.strength.value()}); self.canvas.active=len(entry['regions'])-1
        else:
            self.canvas.active=event[1]
            if event[1]>=0:
                self.strength.blockSignals(True); self.strength.setValue(entry['regions'][event[1]]['strength']); self.strength.blockSignals(False); self.value.setText(str(self.strength.value()))
        self.render(); self.renumber()
    def strength_action(self,*args):
        if not self.strength.isSliderDown(): self.snapshot()
    def strength_changed(self,value):
        self.value.setText(str(value)); entry=self.current(); i=self.canvas.active
        if entry and 0<=i<len(entry['regions']):entry['regions'][i]['strength']=value; self.dirty=True; self.render()
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
                if not isinstance(e['path'],str) or not isinstance(e['regions'],list):raise ValueError('잘못된 작업 파일')
                for r in e['regions']:
                    if len(r['rect'])!=4 or not all(isinstance(v,(int,float)) and 0<=v<=1 for v in r['rect']) or not 2<=r['strength']<=100:raise ValueError('잘못된 모자이크 영역')
            self.populate(entries); self.history=[]; self.project=path; self.dirty=False
        except Exception as exc:QMessageBox.warning(self,'열기 실패',str(exc))
    def export(self):
        if not self.entries or self.busy:return
        folder=QFileDialog.getExistingDirectory(self,'결과를 저장할 상위 폴더')
        if not folder:return
        destination=Path(folder)/('Photo_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6]); destination.mkdir()
        entries=copy.deepcopy(self.ordered()); fmt=self.format.currentText(); ext={'PNG':'png','WEBP':'webp','JPEG':'jpg'}[fmt]
        self.busy=True; self.export_button.setEnabled(False); self.progress.setRange(0,len(entries)); self.progress.setValue(0); self.progress.show(); self.errors=[]
        self.export_next(entries,0,destination,fmt,ext)
    def export_next(self,entries,index,destination,fmt,ext):
        if index==len(entries):
            self.busy=False; self.export_button.setEnabled(True); self.progress.hide()
            message=f'{len(entries)-len(self.errors)}장 저장 완료\n{destination}\nEXIF·XMP·생성 정보 제거 후 검증 완료'
            if self.errors:message+='\n\n실패:\n'+'\n'.join(self.errors[:10])
            QMessageBox.information(self,'내보내기 결과',message); return
        def complete(result):
            if not result[0]:self.errors.append(Path(entries[index]['path']).name+': '+result[1])
            self.progress.setValue(index+1); self.export_next(entries,index+1,destination,fmt,ext)
        self.run_job(self.export_pool,lambda:export_image(entries[index],destination/f'{index+1:03d}.{ext}',fmt),complete)
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
        QTimer.singleShot(1000,app.quit)
    sys.exit(app.exec())
