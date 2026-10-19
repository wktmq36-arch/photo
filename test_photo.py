import unittest,tempfile,os,time
from pathlib import Path
from PIL import Image
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from imaging import export_image
from main import Window
class Tests(unittest.TestCase):
 def test_export(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'source.webp'; im=Image.effect_noise((800,600),100).convert('RGB'); ex=Image.Exif(); ex[270]='secret prompt'; im.save(p,'WEBP',exif=ex,xmp=b'secret prompt')
   for fmt,ext in [('PNG','png'),('WEBP','webp'),('JPEG','jpg')]:
    out=Path(d)/('out.'+ext); export_image({'path':str(p),'regions':[{'rect':[.1,.1,.8,.8],'strength':30}]},out,fmt)
    with Image.open(out) as check:self.assertFalse(check.getexif()); self.assertFalse(set(check.info)&{'exif','xmp','icc_profile'})
    self.assertNotIn(b'secret',out.read_bytes())
   with Image.open(p) as original:self.assertTrue(original.getexif())
 def test_gui(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(300):
    p=Path(d)/f'{i}.webp'; Image.new('RGB',(80,60),(i%255,30,50)).save(p); paths.append(str(p))
   w=Window(); w.add_paths(paths); deadline=time.monotonic()+40
   while w.jobs and time.monotonic()<deadline:app.processEvents(); time.sleep(.001)
   self.assertEqual(w.list.count(),300); self.assertIn(paths[0],w.cache)
   w.region_event(('add',[.1,.1,.6,.6])); self.assertEqual(len(w.current()['regions']),1)
   w.strength.setValue(60); self.assertEqual(w.current()['regions'][0]['strength'],60)
   w.remove_region(); self.assertFalse(w.current()['regions']); w.undo(); self.assertTrue(w.current()['regions'])
   w.remove_selected(); self.assertEqual(w.list.count(),299); w.undo(); self.assertEqual(w.list.count(),300)
   while w.jobs and time.monotonic()<deadline:app.processEvents(); time.sleep(.001)
   w.dirty=False; w.close()
 def test_live_slider_and_keyboard_undo(self):
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(2):
    p=Path(d)/f'image{i}.webp'; Image.effect_noise((800,600),100).convert('RGB').save(p); paths.append(str(p))
   w=Window(); w.show(); w.activateWindow(); w.add_paths(paths); w.list.setCurrentRow(1)
   deadline=time.monotonic()+15
   while w.jobs and time.monotonic()<deadline:app.processEvents(); time.sleep(.001)
   w.region_event(('add',[.1,.1,.8,.8])); before=w.canvas.pixmap.toImage()
   w.strength.setFocus(); w.strength.setSliderDown(True); w.strength.setSliderPosition(80)
   app.processEvents()
   self.assertTrue(w.strength.isSliderDown())
   self.assertEqual(w.current()['regions'][0]['strength'],80)
   self.assertNotEqual(before,w.canvas.pixmap.toImage())
   w.strength.setSliderDown(False)
   QTest.keyClick(w.strength,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier); app.processEvents()
   self.assertEqual(w.list.currentRow(),1)
   self.assertEqual(w.current()['regions'][0]['strength'],20)
   QTest.keyClick(w.strength,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier); app.processEvents()
   self.assertFalse(w.current()['regions'])
   self.assertEqual(w.list.currentRow(),1)
   w.dirty=False; w.close()
 def test_brush_mask(self):
  from imaging import read_pixels,render_regions
  image=Image.effect_noise((400,400),100).convert('RGBA')
  region={'kind':'brush','rect':[.15,.15,.85,.85],'points':[[.2,.2],[.8,.8]],'radius':.05,'strength':70}
  result=render_regions(image,[region])
  self.assertEqual(result.getpixel((80,320)),image.getpixel((80,320)))
  self.assertNotEqual(result.crop((180,180,220,220)).tobytes(),image.crop((180,180,220,220)).tobytes())
 def test_brush_stroke_undo(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'brush.webp'; Image.effect_noise((400,400),100).convert('RGB').save(p)
   w=Window(); w.add_paths([str(p)]); deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents(); time.sleep(.001)
   w.tool.setCurrentIndex(1); self.assertEqual(w.canvas.tool,'brush')
   w.region_event(('brush_start',{'points':[[.2,.2]],'radius':.05}))
   w.region_event(('brush_move',[[.2,.2],[.8,.8]]))
   self.assertEqual(len(w.current()['regions']),1)
   w.undo(); self.assertFalse(w.current()['regions'])
   w.dirty=False; w.close()
 def test_drop_reorders_export_and_undo(self):
  import json
  from PySide6.QtCore import Qt,QMimeData,QPointF
  from PySide6.QtGui import QDropEvent
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i,color in enumerate(['red','green','blue']):
    p=Path(d)/f'{i}.png'; Image.new('RGB',(80,60),color).save(p); paths.append(str(p))
   w=Window(); w.show(); w.add_paths(paths); app.processEvents()
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   ids=[e['id'] for e in w.ordered()]
   mime=QMimeData(); mime.setData(w.list.MIME,json.dumps([ids[0]]).encode())
   index=w.list.model().index(2,0); rect=w.list.visualRect(index)
   drop=QDropEvent(QPointF(rect.right()-2,rect.center().y()),Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   w.list.dropEvent(drop)
   self.assertTrue(drop.isAccepted()); self.assertEqual([e['path'] for e in w.ordered()],[paths[1],paths[2],paths[0]])
   self.assertEqual(w.list.count(),3)
   out=Path(d)/'001.png';export_image(w.ordered()[0],out,'PNG')
   with Image.open(out) as result:self.assertEqual(result.getpixel((0,0))[:3],(0,128,0))
   w.undo(); self.assertEqual([e['path'] for e in w.ordered()],paths)
   w.list.move_ids([ids[1],ids[2]],0)
   self.assertEqual([e['path'] for e in w.ordered()],[paths[1],paths[2],paths[0]])
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_mouse_drag_then_save_reload_and_export(self):
  from unittest.mock import patch
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i,color in enumerate(['red','green','blue','yellow','purple','orange']):
    p=Path(d)/f'{i}.png'; Image.new('RGB',(80,60),color).save(p); paths.append(str(p))
   w=Window(); w.show(); w.activateWindow(); w.add_paths(paths); deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   viewport=w.list.viewport()
   def drag(source,target,after):
    start=w.list.visualItemRect(w.list.item(source)).center()
    rect=w.list.visualItemRect(w.list.item(target))
    finish=QPoint(rect.right()-8 if after else rect.left()+8,rect.center().y())
    QTest.mousePress(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    QTest.mouseMove(viewport,finish,50);app.processEvents()
    self.assertTrue(w.list.dragging)
    self.assertIsNotNone(w.list.drop_target)
    QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,finish)
    app.processEvents()
   drag(0,5,True)
   expected=paths[1:]+paths[:1]
   self.assertEqual([e['path'] for e in w.ordered()],expected)
   drag(5,0,False)
   self.assertEqual([e['path'] for e in w.ordered()],paths)
   drag(0,5,True)
   project=str(Path(d)/'order.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(project,'')):w.save_project()
   import json
   self.assertEqual([e['path'] for e in json.loads(Path(project).read_text(encoding='utf-8'))['images']],expected)
   w.populate([]);w.dirty=False
   with patch('main.QFileDialog.getOpenFileName',return_value=(project,'')):w.load_project()
   self.assertEqual([e['path'] for e in w.ordered()],expected)
   for i,entry in enumerate(w.ordered()):
    out=Path(d)/f'output{i+1:03d}.png';export_image(entry,out,'PNG')
    with Image.open(out) as result,Image.open(expected[i]) as original:self.assertEqual(result.getpixel((0,0))[:3],original.getpixel((0,0)))
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_three_column_row_edges(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  from PySide6.QtWidgets import QListWidgetItem
  from main import ImageList
  app=QApplication.instance() or QApplication([])
  view=ImageList();view.resize(530,400)
  for i in range(1,7):
   item=QListWidgetItem(str(i));item.setData(Qt.ItemDataRole.UserRole,str(i));view.addItem(item)
  view.show();app.processEvents()
  self.assertEqual(view.visualItemRect(view.item(0)).top(),view.visualItemRect(view.item(2)).top())
  self.assertGreater(view.visualItemRect(view.item(3)).top(),view.visualItemRect(view.item(2)).top())
  def drag(source,pos):
   start=view.visualItemRect(view.item(source)).center()
   QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
   QTest.mouseMove(view.viewport(),pos,30);app.processEvents()
   self.assertTrue(view.dragging)
   marker=view.drop_marker
   QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,pos);app.processEvents()
   return marker
  first_row=view.visualItemRect(view.item(2))
  marker=drag(1,QPoint(view.viewport().width()+20,first_row.center().y()))
  self.assertEqual([view.item(i).text() for i in range(6)],['1','3','2','4','5','6'])
  self.assertEqual(marker[1],first_row.top())
  first_row=view.visualItemRect(view.item(0))
  drag(2,QPoint(-20,first_row.center().y()))
  self.assertEqual([view.item(i).text() for i in range(6)],['2','1','3','4','5','6'])
  view.close()
 def test_mosaic_badge_and_resizable_splitter(self):
  from main import MOSAIC_ROLE
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'test.png';Image.new('RGB',(100,100),'red').save(p)
   w=Window();w.show();w.add_paths([str(p)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   self.assertFalse(w.list.item(0).data(MOSAIC_ROLE))
   w.region_event(('add',[.1,.1,.8,.8]));self.assertTrue(w.list.item(0).data(MOSAIC_ROLE))
   w.remove_region();self.assertFalse(w.list.item(0).data(MOSAIC_ROLE))
   w.undo();self.assertTrue(w.list.item(0).data(MOSAIC_ROLE))
   old=w.splitter.sizes()[0];handle=w.splitter.handle(1);center=handle.rect().center()
   QTest.mousePress(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,center)
   QTest.mouseMove(handle,center+QPoint(-100,0),40);app.processEvents()
   QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,handle.rect().center());app.processEvents()
   self.assertLess(w.splitter.sizes()[0],old-40)
   w.dirty=False;w.close()
 def test_batch_strength_preserves_regions_and_undo(self):
  import copy,json
  from unittest.mock import patch
  from PySide6.QtCore import Qt
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(4):
    p=Path(d)/f'{i}.png';Image.effect_noise((200,200),100).convert('RGB').save(p);paths.append(str(p))
   w=Window();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   entries=w.ordered()
   for i in range(3):
    entries[i]['regions']=[{'rect':[.1,.1,.7,.7],'strength':6+i},
     {'kind':'brush','rect':[.15,.15,.85,.85],'radius':.05,'points':[[.2,.2],[.8,.8]],'strength':8-i}]
   w.renumber();w.list.clearSelection()
   for i in [0,1,3]:w.list.item(i).setSelected(True)
   before=copy.deepcopy(w.ordered());history=len(w.history)
   with patch('main.QInputDialog.getInt',return_value=(20,False)):w.batch_strength_dialog()
   self.assertEqual(w.ordered(),before);self.assertEqual(len(w.history),history)
   with patch('main.QInputDialog.getInt',return_value=(20,True)):w.batch_strength_dialog()
   self.assertEqual(len(w.history),history+1)
   for i in [0,1]:
    self.assertTrue(all(r['strength']==20 for r in w.ordered()[i]['regions']))
    for actual,original in zip(w.ordered()[i]['regions'],before[i]['regions']):
     self.assertEqual({k:v for k,v in actual.items() if k!='strength'},{k:v for k,v in original.items() if k!='strength'})
   self.assertEqual(w.ordered()[2],before[2]);self.assertEqual(w.ordered()[3],before[3])
   project=str(Path(d)/'batch.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(project,'')):w.save_project()
   data=json.loads(Path(project).read_text(encoding='utf-8'))
   self.assertEqual(data['images'][0]['regions'][0]['strength'],20)
   w.undo();self.assertEqual(w.ordered(),before)
   w.dirty=False;w.close()
 def test_delete_selects_successor_and_last_predecessor(self):
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(6):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();w.show();w.activateWindow();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.list.setCurrentRow(2);w.list.setFocus()
   QTest.keyClick(w.list,Qt.Key.Key_Delete);app.processEvents()
   self.assertEqual(w.current()['path'],paths[3]);self.assertEqual(len(w.list.selectedItems()),1)
   self.assertEqual(w.title.text(),Path(paths[3]).name)
   QTest.keyClick(w.list,Qt.Key.Key_Delete);app.processEvents()
   self.assertEqual(w.current()['path'],paths[4])
   last=w.list.visualItemRect(w.list.item(w.list.count()-1)).center()
   QTest.mouseClick(w.list.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,last);w.remove_selected()
   self.assertEqual(w.current()['path'],paths[4])
   w.undo();self.assertEqual(w.current()['path'],paths[5])
   w.list.clearSelection()
   w.list.item(1).setSelected(True);w.list.item(3).setSelected(True)
   w.remove_selected();self.assertEqual(w.current()['path'],paths[4])
   w.list.selectAll();w.remove_selected()
   self.assertIsNone(w.current());self.assertEqual(w.list.count(),0)
   self.assertIsNone(w.canvas.pixmap);w.remove_selected()
   w.undo();self.assertEqual(w.list.count(),2)
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_metadata_only_preserves_compressed_pixels(self):
  from imaging import strip_metadata,export_pair
  from PIL.PngImagePlugin import PngInfo
  import struct
  with tempfile.TemporaryDirectory() as d:
   d=Path(d);image=Image.effect_noise((240,200),100).convert('RGB')
   exif=Image.Exif();exif[270]='secret prompt'
   def webp_image_chunks(data):
    offset=12;chunks=[]
    while offset<len(data):
     size=struct.unpack('<I',data[offset+4:offset+8])[0];kind=data[offset:offset+4]
     if kind in [b'VP8 ',b'VP8L',b'ALPH',b'ANIM',b'ANMF']:chunks.append(data[offset:offset+8+size])
     offset+=8+size+(size%2)
    return chunks
   for fmt,ext in [('WEBP','webp'),('PNG','png'),('JPEG','jpg')]:
    source=d/('source.'+ext)
    if fmt=='WEBP':image.save(source,fmt,quality=75,exif=exif,xmp=b'secret prompt')
    elif fmt=='PNG':
     info=PngInfo();info.add_text('parameters','secret prompt');image.save(source,fmt,pnginfo=info,exif=exif)
    else:image.save(source,fmt,exif=exif,progressive=True)
    before=source.read_bytes();out=d/('clean.'+ext);strip_metadata(source,out)
    self.assertEqual(source.read_bytes(),before)
    self.assertNotIn(b'secret',out.read_bytes())
    with Image.open(source) as a,Image.open(out) as b:
     self.assertEqual(a.convert('RGBA').tobytes(),b.convert('RGBA').tobytes());self.assertFalse(b.getexif())
    if fmt=='WEBP':self.assertEqual(webp_image_chunks(before),webp_image_chunks(out.read_bytes()))
   source=d/'source.webp';entry={'path':str(source),'regions':[{'rect':[.1,.1,.9,.9],'strength':50}]}
   export_pair(entry,2,d,'PNG','a')
   self.assertTrue((d/'a_cen/002.png').exists());self.assertTrue((d/'a_uncen/002.webp').exists())
   self.assertEqual(webp_image_chunks(source.read_bytes()),webp_image_chunks((d/'a_uncen/002.webp').read_bytes()))
 def test_export_ui_creates_ordered_folder_pairs(self):
  from unittest.mock import patch
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i,color in enumerate(['red','blue']):
    path=Path(d)/f'{i}.webp';Image.new('RGB',(80,60),color).save(path,lossless=True);paths.append(str(path))
   w=Window();w.add_paths(paths);w.main_check.setChecked(True);w.list.move_ids([w.ordered()[1]['id']],0)
   with patch('main.QFileDialog.getExistingDirectory',return_value=d),patch('main.QInputDialog.getText',return_value=('a',True)),patch('main.QMessageBox.information'):
    w.export();deadline=time.monotonic()+15
    while (w.busy or w.jobs) and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
    self.assertFalse(w.busy);self.assertFalse(w.errors)
   output=next(Path(d).glob('Photo_*'))
   self.assertEqual([p.name for p in (output/'a_main').iterdir()],['002.png'])
   self.assertEqual((output/'a_main/002.png').read_bytes(),(output/'a_cen/002.png').read_bytes())
   with Image.open(output/'a_main/002.png') as main_image:self.assertFalse(main_image.getexif())
   for folder,ext in [('a_cen','png'),('a_uncen','webp')]:
    self.assertEqual(len(list((output/folder).iterdir())),2)
    with Image.open(output/folder/('001.'+ext)) as im:self.assertEqual(im.getpixel((0,0))[:3],(0,0,255))
   w.dirty=False;w.close()
 def test_main_checkbox_persists_and_undoes(self):
  from unittest.mock import patch
  from main import MAIN_ROLE
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(2):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();self.assertFalse(w.main_check.isEnabled());w.add_paths(paths)
   w.main_check.setChecked(True);self.assertTrue(w.ordered()[0]['main_selected'])
   self.assertTrue(w.list.item(0).data(MAIN_ROLE));w.undo();self.assertFalse(w.main_check.isChecked())
   w.main_check.setChecked(True);w.list.setCurrentRow(1);self.assertFalse(w.main_check.isChecked())
   w.list.setCurrentRow(0);self.assertTrue(w.main_check.isChecked())
   project=str(Path(d)/'main.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(project,'')):w.save_project()
   w.main_check.setChecked(False);w.dirty=False
   with patch('main.QFileDialog.getOpenFileName',return_value=(project,'')):w.load_project()
   self.assertTrue(w.main_check.isChecked());self.assertFalse(w.ordered()[1]['main_selected'])
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
if __name__=='__main__':unittest.main()
