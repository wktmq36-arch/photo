import unittest,tempfile,os,time
from pathlib import Path
from PIL import Image
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from imaging import export_image
from main import Window
class Tests(unittest.TestCase):
 def setUp(self):
  from unittest.mock import patch
  from PySide6.QtCore import QSettings
  self.settings_folder=tempfile.TemporaryDirectory();self.addCleanup(self.settings_folder.cleanup)
  settings=QSettings(str(Path(self.settings_folder.name)/'settings.ini'),QSettings.Format.IniFormat)
  mock=patch('main.QSettings',return_value=settings);mock.start();self.addCleanup(mock.stop)

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
   output=Path(d)/'a'
   self.assertTrue(output.is_dir())
   self.assertFalse(list(Path(d).glob('Photo_*')))
   self.assertEqual([p.name for p in (output/'a_main').iterdir()],['001.png'])
   self.assertEqual((output/'a_main/001.png').read_bytes(),(output/'a_cen/002.png').read_bytes())
   with Image.open(output/'a_main/001.png') as main_image:self.assertFalse(main_image.getexif())
   for folder,ext in [('a_cen','png'),('a_uncen','webp')]:
    self.assertEqual(len(list((output/folder).iterdir())),2)
    with Image.open(output/folder/('001.'+ext)) as im:self.assertEqual(im.getpixel((0,0))[:3],(0,0,255))
   stale=output/'stale.txt';stale.write_text('old')
   w.output_checks['uncen'].setChecked(False)
   from PySide6.QtWidgets import QMessageBox
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Yes) as warning,patch('main.QMessageBox.information'):
    w.export();deadline=time.monotonic()+10
    while (w.busy or w.jobs) and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
    warning.assert_called_once();self.assertFalse(w.busy)
   self.assertTrue(stale.exists());self.assertTrue((output/'a_uncen').exists())
   self.assertTrue((output/'a_cen/001.png').exists())
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
 def test_output_choices_and_remembered_folder(self):
  from imaging import export_pair
  from unittest.mock import patch
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);source=root/'source.webp';Image.new('RGB',(80,60),'red').save(source)
   entry={'path':str(source),'regions':[],'main_selected':True}
   for mask in range(1,8):
    dest=root/f'combination{mask}';dest.mkdir()
    choices={key:bool(mask&(1<<i)) for i,key in enumerate(['cen','uncen','main'])}
    files=export_pair(entry,5,dest,'PNG','a',choices)
    self.assertEqual({p.name for p in dest.iterdir()},{'a_'+k for k,v in choices.items() if v})
    self.assertEqual(len(files),sum(choices.values()))
   w=Window();w.add_paths([str(source)])
   w.output_checks['cen'].setChecked(False);w.output_checks['main'].setChecked(False)
   w.export_name.setText('first')
   with patch('main.QFileDialog.getExistingDirectory',return_value=d) as picker,patch('main.QMessageBox.information'):
    w.export();deadline=time.monotonic()+10
    while w.busy or w.jobs:app.processEvents();time.sleep(.001)
    picker.assert_called_once()
    w.export_name.setText('second');w.export()
    while w.busy or w.jobs:app.processEvents();time.sleep(.001)
    picker.assert_called_once()
   self.assertEqual([p.name for p in (root/'second').iterdir()],['second_uncen'])
   w.dirty=False;w.close()
   next_window=Window()
   self.assertEqual(next_window.export_folder,d)
   self.assertFalse(next_window.output_checks['cen'].isChecked())
   self.assertTrue(next_window.output_checks['uncen'].isChecked())
   self.assertEqual(next_window.export_name.text(),'second')
   next_window.close()
 def test_replacing_output_protects_sources_and_parent(self):
  from exporting import prepare_output
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as d:
   parent=Path(d);dest=parent/'a';dest.mkdir();nested=dest/'a_cen';nested.mkdir();(nested/'old.txt').write_text('old')
   outside=parent/'keep.txt';outside.write_text('keep');notice=Mock(return_value=True)
   result=prepare_output(parent,'a',[outside],notice)
   self.assertEqual(result,dest.resolve());notice.assert_called_once_with([nested.resolve()])
   self.assertEqual(list(dest.iterdir()),[]);self.assertEqual(outside.read_text(),'keep')
   nested.mkdir();source=nested/'source.webp';source.write_bytes(b'original');notice.reset_mock()
   with self.assertRaises(ValueError):prepare_output(parent,'a',[source],notice)
   self.assertEqual(source.read_bytes(),b'original');notice.assert_not_called()
   with self.assertRaises(ValueError):prepare_output(parent,'..',[],notice)
 def test_save_uses_current_project_without_prompt(self):
  from unittest.mock import patch
  import json
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';Image.new('RGB',(80,60),'red').save(source)
   w=Window();w.add_paths([str(source)]);project=str(Path(d)/'first.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(project,'')) as picker:
    w.save_project();picker.assert_called_once()
    w.main_check.setChecked(True);w.save_project();picker.assert_called_once()
   self.assertTrue(json.loads(Path(project).read_text(encoding='utf-8'))['images'][0]['main_selected'])
   w.dirty=False
   with patch('main.QFileDialog.getOpenFileName',return_value=(project,'')):w.load_project()
   with patch('main.QFileDialog.getSaveFileName') as picker:w.save_project();picker.assert_not_called()
   second=str(Path(d)/'second.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(second,'')):w.save_project_as()
   self.assertEqual(w.project,second);self.assertTrue(Path(second).exists())
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_sparse_main_selection_has_consecutive_numbers(self):
  from unittest.mock import patch
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(6):
    p=Path(d)/f'{i}.webp';Image.new('RGB',(80,60),(i*30,0,0)).save(p,lossless=True);paths.append(str(p))
   w=Window();w.add_paths(paths)
   for i in [0,3,5]:w.ordered()[i]['main_selected']=True
   w.list.move_ids([w.ordered()[5]['id']],0)
   for main_only in [False,True]:
    name='mainonly' if main_only else 'all';w.export_name.setText(name)
    w.output_checks['cen'].setChecked(not main_only);w.output_checks['uncen'].setChecked(not main_only)
    with patch('main.QFileDialog.getExistingDirectory',return_value=d),patch('main.QMessageBox.information'):
     w.export();deadline=time.monotonic()+10
     while (w.busy or w.jobs) and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
    folder=Path(d)/name/(name+'_main')
    self.assertEqual(sorted(p.name for p in folder.iterdir()),['001.png','002.png','003.png'])
    for i,color in enumerate([150,0,90],1):
     with Image.open(folder/f'{i:03d}.png') as image:self.assertEqual(image.getpixel((0,0))[:3],(color,0,0))
    if not main_only:self.assertEqual(len(list((Path(d)/name/(name+'_cen')).iterdir())),6)
   w.dirty=False;w.close()
 def test_clone_render_and_original_export(self):
  from imaging import render_entry,export_pair
  from PIL import ImageDraw
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.webp';image=Image.new('RGB',(400,300),'blue');ImageDraw.Draw(image).rectangle((0,0,199,299),fill='red');image.save(source,lossless=True)
   stroke={'source':[.2,.5],'points':[[.7,.5],[.75,.5]],'radius':.05,'softness':0}
   entry={'path':str(source),'regions':[],'clones':[stroke],'main_selected':True}
   result=render_entry(image.convert('RGBA'),entry)
   self.assertEqual(result.getpixel((280,150)),(255,0,0,255));self.assertEqual(result.getpixel((280,250)),(0,0,255,255))
   export_pair(entry,1,d,'PNG','a',main_index=1)
   with Image.open(Path(d)/'a_cen/001.png') as processed:self.assertEqual(processed.getpixel((280,150))[:3],(255,0,0))
   with Image.open(Path(d)/'a_uncen/001.webp') as original:self.assertEqual(original.getpixel((280,150))[:3],(0,0,255))
   self.assertEqual((Path(d)/'a_cen/001.png').read_bytes(),(Path(d)/'a_main/001.png').read_bytes())
 def test_clone_mouse_gesture_save_and_undo(self):
  from unittest.mock import patch
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  from PIL import ImageDraw
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';image=Image.new('RGB',(400,300),'blue');ImageDraw.Draw(image).rectangle((0,0,199,299),fill='red');image.save(source)
   w=Window();w.show();w.add_paths([str(source)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.tool.setCurrentIndex(2);w.clone_softness.setValue(0);app.processEvents()
   rect=w.canvas.target
   point=lambda x,y:QPoint(round(rect.x()+rect.width()*x),round(rect.y()+rect.height()*y))
   QTest.mouseClick(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.AltModifier,point(.2,.5))
   self.assertIsNotNone(w.canvas.clone_source)
   history=len(w.history)
   QTest.mousePress(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(.7,.5))
   QTest.mouseMove(w.canvas,point(.75,.5),30)
   QTest.mouseRelease(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point(.75,.5));app.processEvents()
   self.assertEqual(len(w.current()['clones']),1);self.assertEqual(len(w.history),history+1)
   self.assertGreater(w.canvas.pixmap.toImage().pixelColor(280,150).red(),240)
   project=str(Path(d)/'clone.photo.json')
   with patch('main.QFileDialog.getSaveFileName',return_value=(project,'')):w.save_project()
   w.undo();self.assertFalse(w.current()['clones'])
   w.dirty=False
   with patch('main.QFileDialog.getOpenFileName',return_value=(project,'')):w.load_project()
   self.assertEqual(len(w.current()['clones']),1)
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_thumbnail_whole_cell_hover_click_and_modifiers(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(12):
    path=Path(d)/f'{i}.png';Image.new('RGB',(30,180) if i%2 else (180,30),(i*10,30,50)).save(path);paths.append(str(path))
   w=Window();w.show();w.activateWindow();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   view=w.list;viewport=view.viewport()
   for row in range(6):
    cell=view.cell_rect(row)
    for point in [cell.topLeft()+QPoint(3,3),cell.topRight()+QPoint(-3,3),cell.bottomLeft()+QPoint(3,-3),cell.bottomRight()+QPoint(-3,-3),cell.center()]:
     QTest.mouseMove(viewport,point);app.processEvents();self.assertEqual(view.hover_row,row)
     QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point);app.processEvents()
     self.assertEqual(view.currentRow(),row);self.assertEqual(len(view.selectedItems()),1)
     self.assertEqual(w.current()['path'],paths[row]);self.assertEqual(w.title.text(),Path(paths[row]).name)
   QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,view.cell_rect(0).bottomLeft()+QPoint(2,-2))
   QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,view.cell_rect(2).bottomRight()+QPoint(-2,-2))
   self.assertEqual([view.row(item) for item in view.selectedItems()],[0,2])
   QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ShiftModifier,view.cell_rect(4).topLeft()+QPoint(2,2))
   self.assertEqual(sorted(view.row(item) for item in view.selectedItems()),[2,3,4])
   view.scrollToItem(view.item(11));app.processEvents()
   point=view.cell_rect(11).center();QTest.mouseClick(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
   self.assertEqual(view.currentRow(),11);self.assertEqual(len(view.selectedItems()),1)
   w.dirty=False;w.close()
 def test_tool_preferences_survive_restart(self):
  app=QApplication.instance() or QApplication([])
  w=Window();w.tool.setCurrentIndex(1);w.strength.setValue(8);w.brush_size.setValue(75);w.clone_softness.setValue(30);w.close()
  reopened=Window()
  self.assertEqual(reopened.tool.currentIndex(),1);self.assertEqual(reopened.canvas.tool,'brush')
  self.assertEqual(reopened.strength.value(),8);self.assertEqual(reopened.brush_size.value(),75)
  self.assertAlmostEqual(reopened.canvas.brush_radius,.0375);self.assertAlmostEqual(reopened.canvas.clone_softness,.3)
  reopened.close()
 def test_click_and_edit_538_through_540_of_600(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(600):
    p=Path(d)/f'{i+1:03d}.png';Image.new('RGB',(48,80),(i%255,30,50)).save(p);paths.append(str(p))
   w=Window();w.show();w.activateWindow();w.add_paths(paths);deadline=time.monotonic()+30
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   for row in [537,538,539,599]:
    w.list.scrollToItem(w.list.item(row));app.processEvents()
    point=w.list.cell_rect(row).bottomRight()+QPoint(-3,-3)
    QTest.mouseMove(w.list.viewport(),point)
    QTest.mouseClick(w.list.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point)
    deadline=time.monotonic()+10
    while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
    self.assertEqual(w.list.currentRow(),row);self.assertEqual(w.current()['path'],paths[row])
    self.assertIsNotNone(w.canvas.pixmap)
    w.tool.setCurrentIndex(0);rect=w.canvas.target
    start=QPoint(round(rect.x()+rect.width()*.1),round(rect.y()+rect.height()*.1))
    end=QPoint(round(rect.x()+rect.width()*.8),round(rect.y()+rect.height()*.8))
    QTest.mousePress(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
    QTest.mouseMove(w.canvas,end);QTest.mouseRelease(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end)
    self.assertEqual(len(w.current()['regions']),1)
   w.dirty=False;w.close()
 def test_arrow_after_drag_selects_only_one_thumbnail(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(6):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();w.show();w.activateWindow();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   view=w.list;viewport=view.viewport()
   start=view.cell_rect(0).center();target=view.cell_rect(2).topRight()+QPoint(-5,40)
   QTest.mousePress(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start)
   QTest.mouseMove(viewport,target,30);QTest.mouseRelease(viewport,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,target)
   self.assertEqual(view.currentRow(),2)
   for key,row in [(Qt.Key.Key_Right,3),(Qt.Key.Key_Right,4),(Qt.Key.Key_Left,3)]:
    QTest.keyClick(view,key);app.processEvents()
    self.assertEqual(view.currentRow(),row)
    self.assertEqual([view.row(item) for item in view.selectedItems()],[row])
    self.assertEqual(w.title.text(),Path(w.current()['path']).name)
   view.selectAll();QTest.keyClick(view,Qt.Key.Key_Left);app.processEvents()
   self.assertEqual([view.row(item) for item in view.selectedItems()],[2])
   w.dirty=False;w.close()
 def test_delete_undo_reuses_thumbnails_without_loading(self):
  from unittest.mock import patch
  from PySide6.QtCore import Qt
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(600):
    p=Path(d)/f'{i}.png';Image.new('RGB',(40,60),'red').save(p);paths.append(str(p))
   w=Window();w.add_paths(paths);deadline=time.monotonic()+30
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   keep={w.list.item(i).data(Qt.ItemDataRole.UserRole):w.list.item(i) for i in range(600) if i not in [537,538,539]}
   w.list.clearSelection()
   for i in [537,538,539]:w.list.item(i).setSelected(True)
   w.remove_selected();self.assertEqual(w.list.count(),597)
   with patch.object(w,'load_thumb',wraps=w.load_thumb) as reader:
    w.undo();app.processEvents()
    reader.assert_not_called()
    self.assertEqual(w.list.count(),600)
    for i in range(600):
     item=w.list.item(i);eid=item.data(Qt.ItemDataRole.UserRole)
     if eid in keep:self.assertIs(item,keep[eid])
     self.assertFalse(item.icon().isNull())
    self.assertFalse(w.thumb_waiters)
    w.list.selectAll();w.remove_selected();w.undo();app.processEvents();reader.assert_not_called()
   w.dirty=False;w.close()
 def test_close_save_discard_cancel_and_save_failure(self):
  from unittest.mock import patch
  from PySide6.QtGui import QCloseEvent
  from PySide6.QtWidgets import QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';Image.new('RGB',(80,60),'red').save(source)
   w=Window();w.add_paths([str(source)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   B=QMessageBox.StandardButton
   with patch('main.QMessageBox.exec',return_value=B.Cancel):
    event=QCloseEvent();w.closeEvent(event);self.assertFalse(event.isAccepted());self.assertTrue(w.dirty)
   with patch('main.QMessageBox.exec',return_value=B.Save),patch('main.QFileDialog.getSaveFileName',return_value=('','')):
    event=QCloseEvent();w.closeEvent(event);self.assertFalse(event.isAccepted());self.assertTrue(w.dirty)
   project=str(Path(d)/'saved.photo.json')
   with patch('main.QMessageBox.exec',return_value=B.Save),patch('main.QFileDialog.getSaveFileName',return_value=(project,'')):
    event=QCloseEvent();w.closeEvent(event);self.assertTrue(event.isAccepted());self.assertFalse(w.dirty);self.assertTrue(Path(project).exists())
   w.dirty=True;w.project=str(Path(d)/'missing'/'fail.photo.json')
   with patch('main.QMessageBox.exec',return_value=B.Save),patch('main.QMessageBox.warning'):
    event=QCloseEvent();w.closeEvent(event);self.assertFalse(event.isAccepted());self.assertTrue(w.dirty)
   with patch('main.QMessageBox.exec',return_value=B.Discard):
    event=QCloseEvent();w.closeEvent(event);self.assertTrue(event.isAccepted())
   w.dirty=False
   with patch('main.QMessageBox.exec') as dialog:
    event=QCloseEvent();w.closeEvent(event);self.assertTrue(event.isAccepted());dialog.assert_not_called()
   w.close()
 def test_selection_count_and_bulk_main_context_menu(self):
  from unittest.mock import patch
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  from PySide6.QtWidgets import QMenu
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(5):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();w.show();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   view=w.list
   QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,view.cell_rect(0).center())
   for row in [2,4]:QTest.mouseClick(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,view.cell_rect(row).center())
   self.assertEqual(w.selection_count.text(),'선택 3장')
   self.assertEqual(w.bottom_selection_count.text(),'선택 3장 / 전체 5장')
   QTest.mousePress(view.viewport(),Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,view.cell_rect(2).center())
   self.assertEqual(len(view.selectedItems()),3)
   QTest.mouseRelease(view.viewport(),Qt.MouseButton.RightButton,Qt.KeyboardModifier.NoModifier,view.cell_rect(2).center())
   menu=QMenu()
   with patch('main.QMenu',return_value=menu),patch.object(menu,'exec',side_effect=lambda pos:menu.actions()[0].trigger()):
    w.thumbnail_context_menu(view.cell_rect(2).center())
   self.assertIn('3장',menu.actions()[0].text())
   self.assertEqual([i for i,e in enumerate(w.ordered()) if e['main_selected']],[0,2,4])
   self.assertEqual(w.selection_count.text(),'선택 3장')
   self.assertEqual(w.bottom_selection_count.text(),'선택 3장 / 전체 5장')
   w.undo();self.assertFalse(any(e['main_selected'] for e in w.ordered()))
   view.selectAll();self.assertEqual(w.selection_count.text(),'선택 5장')
   ids=[e['id'] for e in w.ordered()];w.set_main_for_ids(ids,True)
   menu2=QMenu()
   with patch('main.QMenu',return_value=menu2),patch.object(menu2,'exec',side_effect=lambda pos:menu2.actions()[1].trigger()):
    w.thumbnail_context_menu(view.cell_rect(1).center())
   self.assertFalse(any(e['main_selected'] for e in w.ordered()))
   w.undo();self.assertTrue(all(e['main_selected'] for e in w.ordered()))
   w.dirty=False;w.close()
 def test_main_checkbox_returns_focus_for_up_down(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(12):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();w.show();w.activateWindow();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   QTest.mouseClick(w.list.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.list.cell_rect(0).center())
   w.tool.setFocus();QTest.mouseClick(w.main_check,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(8,w.main_check.height()//2))
   app.processEvents();self.assertTrue(w.ordered()[0]['main_selected']);self.assertIs(app.focusWidget(),w.list)
   tool=w.tool.currentIndex();QTest.keyClick(app.focusWidget(),Qt.Key.Key_Down);app.processEvents()
   self.assertGreater(w.list.currentRow(),0);self.assertEqual(len(w.list.selectedItems()),1);self.assertEqual(w.tool.currentIndex(),tool)
   QTest.keyClick(app.focusWidget(),Qt.Key.Key_Up);app.processEvents();self.assertEqual(w.list.currentRow(),0)
   QTest.mouseClick(w.main_check,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(8,w.main_check.height()//2));app.processEvents()
   self.assertFalse(w.ordered()[0]['main_selected']);self.assertIs(app.focusWidget(),w.list)
   QTest.keyClick(app.focusWidget(),Qt.Key.Key_Down);app.processEvents();self.assertGreater(w.list.currentRow(),0)
   w.dirty=False;w.close()
 def test_wheel_zoom_anchor_pan_and_edit_coordinates(self):
  from PySide6.QtCore import Qt,QPoint,QPointF
  from PySide6.QtGui import QWheelEvent
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'zoom.png';Image.new('RGB',(400,400),'red').save(path)
   w=Window();w.show();w.activateWindow();w.add_paths([str(path)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   canvas=w.canvas;point=QPointF(canvas.rect().center());before=canvas.normalized(point)
   wheel=QWheelEvent(point,QPointF(canvas.mapToGlobal(point.toPoint())),QPoint(),QPoint(0,480),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
   app.sendEvent(canvas,wheel);app.processEvents()
   self.assertGreater(canvas.zoom,2);after=canvas.normalized(point)
   self.assertAlmostEqual(before[0],after[0],places=5);self.assertAlmostEqual(before[1],after[1],places=5)
   pan=QPointF(canvas.pan)
   QTest.mousePress(canvas,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.NoModifier,point.toPoint())
   QTest.mouseMove(canvas,point.toPoint()+QPoint(30,20));QTest.mouseRelease(canvas,Qt.MouseButton.MiddleButton,Qt.KeyboardModifier.NoModifier,point.toPoint()+QPoint(30,20))
   self.assertAlmostEqual(canvas.pan.x()-pan.x(),30);self.assertAlmostEqual(canvas.pan.y()-pan.y(),20)
   start=canvas.rect().center();end=start+QPoint(35,30);a,b=canvas.normalized(start);c,e=canvas.normalized(end)
   QTest.mousePress(canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start);QTest.mouseMove(canvas,end);QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,end)
   rect=w.current()['regions'][0]['rect']
   for actual,expected in zip(rect,[a,b,c,e]):self.assertAlmostEqual(actual,expected,places=5)
   canvas.reset_view();self.assertEqual(canvas.zoom,1);self.assertEqual(canvas.pan,QPointF())
   w.dirty=False;w.close()
 def test_panel_layout_persists_and_history_updates(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'history.png';Image.new('RGB',(80,60),'red').save(path)
   w=Window();w.show();w.add_paths([str(path)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   self.assertEqual(w.recent_projects,[])
   w.region_event(('add',[.1,.1,.6,.6]));w.undo()
   w.history_dock.hide();w.splitter.setSizes([300,700]);app.processEvents()
   ratio=w.splitter.sizes()[0]/sum(w.splitter.sizes());w.dirty=False;w.close()
   reopened=Window();reopened.show();app.processEvents()
   restored=reopened.splitter.sizes()[0]/sum(reopened.splitter.sizes())
   self.assertAlmostEqual(ratio,restored,delta=.04);self.assertTrue(reopened.history_dock.isHidden())
   reopened.history_toggle.click();app.processEvents();self.assertTrue(reopened.history_dock.isVisible())
   reopened.close()
 def test_saved_project_sidebar_click_switch_and_persistence(self):
  import json
  from unittest.mock import patch
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  from PySide6.QtWidgets import QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   sources=[]
   for i in range(2):
    path=Path(d)/f'image{i}.png';Image.new('RGB',(80,60),'red').save(path);sources.append(str(path))
   first=str(Path(d)/'first.photo.json');second=str(Path(d)/'second.photo.json')
   w=Window();w.show();w.add_paths([sources[0]]);self.assertTrue(w.write_project(first))
   w.populate([{'id':'second','path':sources[1],'regions':[]}]);self.assertTrue(w.write_project(second))
   self.assertEqual(w.recent_projects,[second,first])
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   item=w.history_list.item(1)
   QTest.mouseClick(w.history_list.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,w.history_list.visualItemRect(item).center());app.processEvents()
   self.assertEqual(w.project,first);self.assertEqual(w.current()['path'],sources[0])
   w.main_check.setChecked(True)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Cancel):w.open_recent_project(w.history_list.item(1))
   self.assertEqual(w.project,first);self.assertTrue(w.dirty)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Save):w.open_recent_project(w.history_list.item(1))
   self.assertEqual(w.project,second)
   self.assertTrue(json.loads(Path(first).read_text(encoding='utf-8'))['images'][0]['main_selected'])
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
   reopened=Window();self.assertEqual(reopened.recent_projects,[second,first])
   with patch('main.QMessageBox.warning') as warning:
    self.assertFalse(reopened.open_project(str(Path(d)/'missing.photo.json')));warning.assert_called_once()
   self.assertIsNone(reopened.project);reopened.close()
 def test_each_tool_keeps_its_own_brush_size(self):
  app=QApplication.instance() or QApplication([])
  w=Window()
  for index,size in [(0,25),(1,90),(2,15)]:w.tool.setCurrentIndex(index);w.brush_size.setValue(size)
  for index,size in [(1,90),(0,25),(2,15),(1,90)]:
   w.tool.setCurrentIndex(index);self.assertEqual(w.brush_size.value(),size)
   self.assertAlmostEqual(w.canvas.brush_radius,size/2000)
  w.close();reopened=Window()
  self.assertEqual(reopened.tool.currentIndex(),1);self.assertEqual(reopened.brush_size.value(),90)
  reopened.tool.setCurrentIndex(2);self.assertEqual(reopened.brush_size.value(),15)
  reopened.tool.setCurrentIndex(0);self.assertEqual(reopened.brush_size.value(),25);reopened.close()
 def test_icon_tool_buttons_exclusive_and_restore_sizes(self):
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  w=Window();w.show();w.activateWindow();app.processEvents()
  QTest.mouseClick(w.tool.buttons[1],Qt.MouseButton.LeftButton);w.brush_size.setValue(85)
  QTest.mouseClick(w.tool.buttons[2],Qt.MouseButton.LeftButton);w.brush_size.setValue(12)
  QTest.mouseClick(w.tool.buttons[1],Qt.MouseButton.LeftButton)
  self.assertEqual(w.canvas.tool,'brush');self.assertEqual(w.brush_size.value(),85)
  self.assertEqual([button.isChecked() for button in w.tool.buttons],[False,True,False])
  self.assertTrue(all(not button.icon().isNull() for button in w.tool.buttons))
  self.assertIs(app.focusWidget(),w.list)
  QTest.mouseClick(w.tool.buttons[2],Qt.MouseButton.LeftButton)
  self.assertEqual(w.brush_size.value(),12);self.assertEqual(w.canvas.tool,'clone')
  w.close()
 def test_redo_multiple_edits_and_new_branch(self):
  import copy
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(3):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(p);paths.append(str(p))
   w=Window();w.show();w.activateWindow();states=[[]]
   w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   states.append(copy.deepcopy(w.ordered()))
   w.region_event(('add',[.1,.1,.6,.6]));states.append(copy.deepcopy(w.ordered()))
   w.main_check.setChecked(True);states.append(copy.deepcopy(w.ordered()))
   w.region_event(('clone_start',{'source':[.1,.1],'points':[[.7,.7]],'radius':.02,'softness':.5}));states.append(copy.deepcopy(w.ordered()))
   w.list.move_ids([w.ordered()[0]['id']],3);states.append(copy.deepcopy(w.ordered()))
   w.remove_selected();states.append(copy.deepcopy(w.ordered()))
   for expected in reversed(states[:-1]):w.undo();self.assertEqual(w.ordered(),expected)
   self.assertTrue(w.redo_button.isEnabled());self.assertFalse(w.undo_button.isEnabled())
   w.list.setFocus()
   for i,expected in enumerate(states[1:]):
    key=Qt.Key.Key_Y if i%2==0 else Qt.Key.Key_Z
    mods=Qt.KeyboardModifier.ControlModifier if i%2==0 else Qt.KeyboardModifier.ControlModifier|Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(w.list,key,mods);app.processEvents();self.assertEqual(w.ordered(),expected)
   self.assertFalse(w.redo_button.isEnabled());w.undo();self.assertTrue(w.redo_stack)
   w.region_event(('add',[.2,.2,.8,.8]));self.assertFalse(w.redo_stack);self.assertFalse(w.redo_button.isEnabled())
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_incremental_clone_matches_final_soft_edges(self):
  from imaging import ClonePreview,render_clones
  image=Image.effect_noise((480,360),60).convert('RGBA')
  for softness in [0,.5,1]:
   stroke={'source':[.02,.05],'points':[[.4,.4]],'radius':.05,'softness':softness}
   preview=ClonePreview(image,stroke);points=[[.4,.4]]
   for i in range(80):
    points.append([.4+i*.003,.4+(.04 if i%3 else -.03)])
    preview.update(points)
   stroke['points']=points
   self.assertEqual(preview.result.tobytes(),render_clones(image,[stroke]).tobytes())
 def test_clone_drag_does_not_replay_committed_strokes(self):
  from unittest.mock import patch
  from imaging import render_clones,render_entry
  from main import to_qimage
  from PySide6.QtGui import QImage
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'clone.png';Image.effect_noise((800,600),60).convert('RGB').save(path)
   w=Window();w.add_paths([str(path)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.current()['clones']=[{'source':[.1,.1],'points':[[.2,.2+i*.01],[.25,.2+i*.01]],'radius':.02,'softness':.5} for i in range(20)]
   w.render()
   with patch('main.render_clones',wraps=render_clones) as replay,patch.object(w,'renumber',wraps=w.renumber) as renumber:
    w.region_event(('clone_start',{'source':[.2,.2],'points':[[.5,.5]],'radius':.025,'softness':.5}))
    count=replay.call_count
    points=[[.5,.5]]
    for i in range(60):
     points.append([.5+i*.002,.5+i*.001]);w.region_event(('clone_move',points.copy()));w.flush_clone_preview()
    w.region_event(('clone_end',points.copy()))
    self.assertEqual(replay.call_count,count);self.assertEqual(renumber.call_count,1)
   expected=to_qimage(render_entry(w.cache[str(path)],w.current()))
   self.assertEqual(w.canvas.pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888),expected)
   w.dirty=False;w.close()
 def test_ctrl_drag_pans_without_editing_for_all_tools(self):
  from PySide6.QtCore import Qt,QPoint,QPointF
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'pan.png';Image.new('RGB',(400,400),'red').save(path)
   w=Window();w.show();w.add_paths([str(path)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.canvas.zoom=2;w.canvas.update_target()
   for index in range(3):
    w.tool.setCurrentIndex(index);old=QPointF(w.canvas.pan);history=len(w.history);start=w.canvas.rect().center()
    QTest.mousePress(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier,start)
    QTest.mouseMove(w.canvas,start+QPoint(40,25));QTest.mouseRelease(w.canvas,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,start+QPoint(40,25))
    self.assertAlmostEqual(w.canvas.pan.x()-old.x(),40);self.assertAlmostEqual(w.canvas.pan.y()-old.y(),25)
    self.assertFalse(w.current()['regions']);self.assertFalse(w.current()['clones']);self.assertEqual(len(w.history),history)
   w.dirty=False;w.close()
 def test_lower_panel_drag_and_restart_layout(self):
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  w=Window();w.show();app.processEvents();splitter=w.preview_splitter
  before=splitter.sizes()[0];handle=splitter.handle(1);center=handle.rect().center()
  QTest.mousePress(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,center)
  QTest.mouseMove(handle,center+QPoint(0,-70),40);app.processEvents()
  QTest.mouseRelease(handle,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,handle.rect().center());app.processEvents()
  self.assertLess(splitter.sizes()[0],before-30)
  ratio=splitter.sizes()[0]/sum(splitter.sizes());w.close()
  reopened=Window();reopened.show();app.processEvents()
  self.assertAlmostEqual(ratio,reopened.preview_splitter.sizes()[0]/sum(reopened.preview_splitter.sizes()),delta=.04)
  reopened.close()
 def test_declining_export_replacement_keeps_existing_files(self):
  from exporting import prepare_output
  from unittest.mock import Mock,patch
  from PySide6.QtWidgets import QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);dest=root/'a';dest.mkdir();nested=dest/'a_cen';nested.mkdir();old=nested/'001.png';old.write_bytes(b'keep existing')
   notify=Mock(return_value=False)
   self.assertIsNone(prepare_output(root,'a',[],notify));notify.assert_called_once()
   self.assertEqual(old.read_bytes(),b'keep existing')
   source=root/'source.png';Image.new('RGB',(80,60),'red').save(source)
   w=Window();w.add_paths([str(source)]);w.export_folder=d
   for answer in [QMessageBox.StandardButton.No,0]:
    with patch('main.QMessageBox.exec',return_value=answer) as question:
     w.export();question.assert_called_once()
    self.assertFalse(w.busy);self.assertEqual(old.read_bytes(),b'keep existing')
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.No):self.assertFalse(w.confirm_output_replacement(dest))
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_replace_only_selected_output_folders(self):
  from exporting import prepare_output
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as d:
   parent=Path(d)
   for mask in range(1,8):
    name=f'case{mask}';root=parent/name;root.mkdir()
    unrelated=root/'keep.txt';unrelated.write_bytes(b'keep')
    choices={key:bool(mask&(1<<i)) for i,key in enumerate(['cen','uncen','main'])}
    for kind in choices:
     folder=root/(name+'_'+kind);folder.mkdir();(folder/'old.bin').write_bytes(kind.encode())
    notice=Mock(return_value=True)
    prepare_output(parent,name,[],notice,choices)
    for kind,selected in choices.items():
     folder=root/(name+'_'+kind)
     if selected:self.assertFalse(folder.exists())
     else:self.assertEqual((folder/'old.bin').read_bytes(),kind.encode())
    self.assertEqual(unrelated.read_bytes(),b'keep')
    self.assertEqual(set(notice.call_args.args[0]),{root/(name+'_'+kind) for kind,selected in choices.items() if selected})
 def test_main_only_reexport_preserves_cen_and_uncen(self):
  from unittest.mock import patch
  from PySide6.QtWidgets import QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.webp';Image.new('RGB',(80,60),'red').save(source)
   w=Window();w.add_paths([str(source)]);w.main_check.setChecked(True);w.export_folder=d
   with patch('main.QMessageBox.information'):
    w.export();deadline=time.monotonic()+10
    while (w.busy or w.jobs) and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   root=Path(d)/'a';before={str(p.relative_to(root)):p.read_bytes() for folder in ['a_cen','a_uncen'] for p in (root/folder).iterdir()}
   stale=root/'a_main/999.png';stale.write_bytes(b'old')
   w.output_checks['cen'].setChecked(False);w.output_checks['uncen'].setChecked(False)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Yes),patch('main.QMessageBox.information'):
    w.export();deadline=time.monotonic()+10
    while (w.busy or w.jobs) and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   self.assertFalse(stale.exists());self.assertTrue((root/'a_main/001.png').exists())
   for relative,data in before.items():self.assertEqual((root/relative).read_bytes(),data)
   w.dirty=False;w.close()
 def test_external_files_drop_inserts_at_indicator_and_undoes_once(self):
  import json
  from PySide6.QtCore import Qt,QPointF,QMimeData,QUrl
  from PySide6.QtGui import QDragEnterEvent,QDragMoveEvent,QDragLeaveEvent,QDropEvent
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(4):
    p=Path(d)/f'{i}.png';Image.new('RGB',(80,60),(i*40,0,0)).save(p);paths.append(str(p))
   w=Window();w.show();w.add_paths([paths[0],paths[3]]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   old=w.list.item(1);rect=w.list.cell_rect(1);pos=rect.topLeft();pos.setX(pos.x()+3);pos.setY(pos.y()+40)
   mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(path) for path in [paths[1],paths[2],paths[0]]])
   enter=QDragEnterEvent(pos,Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   w.list.dragEnterEvent(enter);self.assertTrue(enter.isAccepted());self.assertEqual(w.list.drop_target,1)
   move=QDragMoveEvent(pos,Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   w.list.dragMoveEvent(move);self.assertEqual(w.list.drop_target,1)
   w.list.dragLeaveEvent(QDragLeaveEvent());self.assertIsNone(w.list.drop_target)
   drop=QDropEvent(QPointF(pos),Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   history=len(w.history);w.list.dropEvent(drop)
   self.assertTrue(drop.isAccepted());self.assertEqual(drop.dropAction(),Qt.DropAction.CopyAction)
   self.assertEqual([e['path'] for e in w.ordered()],paths);self.assertIs(w.list.item(3),old)
   self.assertEqual(len(w.history),history+1);self.assertEqual(w.selection_count.text(),'선택 2장')
   self.assertIsNone(w.list.drop_target);self.assertTrue(all(Path(path).exists() for path in paths))
   saved=str(Path(d)/'inserted.photo.json');w.write_project(saved)
   self.assertEqual([e['path'] for e in json.loads(Path(saved).read_text(encoding='utf-8'))['images']],paths)
   w.undo();self.assertEqual([e['path'] for e in w.ordered()],[paths[0],paths[3]])
   w.redo();self.assertEqual([e['path'] for e in w.ordered()],paths)
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_tool_settings_and_noop_slider_do_not_use_undo_slots(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'settings.png';Image.new('RGB',(80,60),'red').save(path)
   w=Window();w.add_paths([str(path)]);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.region_event(('add',[.1,.1,.8,.8]));before=len(w.history)
   for i in range(100):
    w.tool.setCurrentIndex(i%3);w.brush_size.setValue(5+i%190);w.clone_softness.setValue(i%101)
    w.strength.setSliderDown(True);w.strength.setSliderDown(False)
   self.assertEqual(len(w.history),before)
   size=w.brush_size.value();tool=w.tool.currentIndex();w.undo()
   self.assertFalse(w.current()['regions']);self.assertEqual(w.brush_size.value(),size);self.assertEqual(w.tool.currentIndex(),tool)
   w.dirty=False;w.close()
 def test_history_capacity_and_shared_unchanged_entries(self):
  from main import HISTORY_LIMIT
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(2):
    path=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(path);paths.append(str(path))
   w=Window();w.add_paths(paths)
   for i in range(HISTORY_LIMIT+10):
    w.snapshot('편집');w.current()['main_selected']=not w.current()['main_selected']
   self.assertEqual(len(w.history),1000)
   self.assertIs(w.history[-1][0][1],w.history[-2][0][1])
   w.current()['clones']=[{'source':[.1,.1],'points':[[.2,.2]],'radius':.02,'softness':.5}]
   w.snapshot();w.current()['main_selected']=not w.current()['main_selected'];w.snapshot()
   self.assertIs(w.history[-1][0][0]['clones'][0],w.history[-2][0][0]['clones'][0])
   for _ in range(60):w.undo()
   self.assertEqual(len(w.redo_stack),60)
   for _ in range(60):w.redo()
   self.assertEqual(len(w.history),1000)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_clear_all_mosaics_preserves_clone_and_can_undo(self):
  import copy
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(2):
    path=Path(d)/f'{i}.png';Image.new('RGB',(80,60),'red').save(path);paths.append(str(path))
   w=Window();w.add_paths(paths);deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   for entry in w.ordered():
    entry['regions']=[{'rect':[.1,.1,.8,.8],'strength':20}]
    entry['clones']=[{'source':[.1,.1],'points':[[.7,.7]],'radius':.02,'softness':.5}]
   before=copy.deepcopy(w.ordered());w.clear_mosaics([w.ordered()[0]['id']])
   self.assertFalse(w.ordered()[0]['regions']);self.assertTrue(w.ordered()[1]['regions']);self.assertTrue(w.ordered()[0]['clones'])
   w.undo();self.assertEqual(w.ordered(),before)
   w.clear_mosaics(list(w.entries));self.assertFalse(any(e['regions'] for e in w.ordered()))
   self.assertTrue(all(e['clones'] for e in w.ordered()));w.undo();self.assertEqual(w.ordered(),before)
   w.redo();self.assertFalse(any(e['regions'] for e in w.ordered()))
   w.dirty=False;w.close()
if __name__=='__main__':unittest.main()
