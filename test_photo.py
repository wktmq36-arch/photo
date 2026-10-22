import unittest,tempfile,os,time
from pathlib import Path
from PIL import Image
os.environ['QT_QPA_PLATFORM']='offscreen'
from PySide6.QtWidgets import QApplication
from imaging import export_image
from main import Window
class Tests(unittest.TestCase):
 def test_crop_stretches_all_kept_pixels_to_original_size_without_padding(self):
  from imaging import stretch_crop
  image=Image.new('RGBA',(200,300),'white')
  image.paste('red',(0,50,50,250));image.paste('green',(50,50,150,250));image.paste('blue',(150,50,200,250))
  original=image.tobytes();result=stretch_crop(image,[0.,1/6,1.,5/6])
  expected=image.crop((0,50,200,250)).resize((200,300),Image.Resampling.LANCZOS)
  self.assertEqual(result.size,(200,300));self.assertEqual(result.tobytes(),expected.tobytes());self.assertEqual(image.tobytes(),original)
  for y in (0,150,299):
   self.assertEqual(result.getpixel((40,y)),(255,0,0,255));self.assertEqual(result.getpixel((160,y)),(0,0,255,255))
  self.assertNotIn((255,255,255,255),result.getdata())
 def test_crop_mode_trim_preview_apply_save_and_undo(self):
  from imaging import read_pixels,render_entry
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'source.png';image=Image.new('RGB',(200,300),'white');image.paste('red',(0,50,50,250));image.paste('green',(50,50,150,250));image.paste('blue',(150,50,200,250));image.save(path)
   original=path.read_bytes();expected=read_pixels(path).crop((0,50,200,250)).resize((200,300),Image.Resampling.LANCZOS)
   w=Window();w.show();w.add_paths([str(path)]);app.processEvents();editor=w.start_crop_mode()
   self.assertFalse(editor.isWindow());self.assertIs(w.editor_stack.currentWidget(),editor)
   editor.trims['top'].setValue(50);editor.trims['bottom'].setValue(50);editor.result_check.setChecked(True)
   self.assertEqual(editor.preview.pixmap.size().width(),200);self.assertEqual(editor.preview.pixmap.toImage().pixelColor(40,0).getRgb(),(255,0,0,255))
   self.assertEqual(editor.preview.pixmap.toImage().pixelColor(160,299).getRgb(),(0,0,255,255))
   editor.accepted.emit();self.assertIsNone(w.crop_editor);self.assertIn('crop_source',w.current())
   self.assertEqual(render_entry(read_pixels(path),w.current()).tobytes(),expected.tobytes());self.assertEqual(path.read_bytes(),original)
   w.undo();self.assertNotIn('crop_source',w.current());w.redo();self.assertIn('crop_source',w.current())
   project=str(Path(d)/'crop.photo.json');w.write_project(project);self.assertTrue(w.open_project(project))
   output=Path(d)/'cropped.png';export_image(w.current(),output,'PNG')
   with Image.open(output) as saved:self.assertEqual(saved.size,(200,300));self.assertEqual(saved.convert('RGBA').tobytes(),expected.tobytes());self.assertFalse(saved.info)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_crop_preserves_existing_mosaic_and_batch_changes_after_crop(self):
  import copy
  from imaging import read_pixels,render_entry,stretch_crop,all_regions
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'source.png';Image.effect_noise((240,320),100).convert('RGB').save(path)
   w=Window();w.add_paths([str(path)]);region={'rect':[.1,.2,.9,.8],'strength':50};w.current()['regions']=[region]
   original=copy.deepcopy(w.current());raw=read_pixels(path);rect=[0.,.15,1.,.85]
   expected=stretch_crop(render_entry(raw,original),rect);w.apply_crop(rect)
   self.assertEqual(render_entry(raw,w.current()).tobytes(),expected.tobytes());self.assertEqual(len(all_regions(w.current())),1)
   w.apply_batch_strength([w.current()['id']],8);original['regions'][0]['strength']=8
   self.assertEqual(all_regions(w.current())[0]['strength'],8);self.assertEqual(render_entry(raw,w.current()).tobytes(),stretch_crop(render_entry(raw,original),rect).tobytes())
   second=[.1,.1,.9,.9];previous=render_entry(raw,w.current());w.apply_crop(second)
   self.assertEqual(render_entry(raw,w.current()).tobytes(),stretch_crop(previous,second).tobytes())
   from cut_editor import CutEditor
   from composition import decode_asset
   editor=CutEditor(w.current(),w.ordered(),[w.list.item(0).icon()]);editor.copy_region([0.,0.,1.,1.])
   self.assertEqual(decode_asset(editor.clipboard[1]).tobytes(),render_entry(raw,w.current()).tobytes());editor.reject()
   w.clear_mosaics([w.current()['id']]);self.assertFalse(all_regions(w.current()));w.undo();self.assertEqual(len(all_regions(w.current())),1)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_crop_close_cancel_and_save_while_selecting(self):
  from unittest.mock import patch
  from PySide6.QtWidgets import QMessageBox
  from PySide6.QtGui import QCloseEvent
  from imaging import validate_edits
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'source.png';Image.new('RGB',(200,300),'red').save(path)
   w=Window();w.add_paths([str(path)]);project=str(Path(d)/'crop.photo.json');w.write_project(project)
   editor=w.start_crop_mode();editor.trims['top'].setValue(20)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Cancel):
    event=QCloseEvent();w.closeEvent(event);self.assertFalse(event.isAccepted())
   self.assertIs(w.crop_editor,editor);self.assertNotIn('crop_source',w.current())
   self.assertTrue(w.write_project(project));self.assertIsNone(w.crop_editor);validate_edits(w.current());self.assertIn('crop_source',w.current())
   for rect in ([0,0,1,0],[0,-1,1,1],[0,0,float('nan'),1]):
    with self.assertRaises(ValueError):validate_edits({'regions':[],'crop_source':{'rect':rect,'edits':{'regions':[]}}})
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_main_only_view_keeps_order_and_navigates_visible_items(self):
  import json
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(7):
    path=Path(d)/f'{i}.png';Image.new('RGB',(80,60),(i*30,0,0)).save(path);paths.append(str(path))
   w=Window();w.show();w.activateWindow();w.add_paths(paths)
   for i in (1,3,5):w.ordered()[i]['main_selected']=True
   w.renumber();w.dirty=False;history=len(w.history);items=[w.list.item(i) for i in range(7)]
   w.main_only.setChecked(True);app.processEvents()
   self.assertEqual(w.visible_rows(),[1,3,5]);self.assertEqual(w.list.currentRow(),1);self.assertFalse(w.dirty);self.assertEqual(len(w.history),history)
   w.list.setFocus();QTest.keyClick(w.list,Qt.Key.Key_Right);self.assertEqual(w.list.currentRow(),3)
   QTest.keyClick(w.list,Qt.Key.Key_Right);self.assertEqual(w.list.currentRow(),5)
   QTest.keyClick(w.list,Qt.Key.Key_Right);self.assertEqual(w.list.currentRow(),5)
   for row in (1,3,5):self.assertEqual(w.list.row_at(w.list.cell_rect(row).center()),row)
   rect=w.list.visualItemRect(w.list.item(3));self.assertEqual(w.list.target_at(rect.topLeft()),3)
   QTest.keyClick(w.list,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier)
   self.assertEqual([w.list.row(item) for item in w.list.selectedItems()],[1,3,5])
   self.assertTrue(all(not w.list.item(row).isSelected() for row in (0,2,4,6)))
   project=str(Path(d)/'filtered.photo.json');w.write_project(project)
   self.assertEqual([e['path'] for e in json.loads(Path(project).read_text(encoding='utf-8'))['images']],paths)
   w.main_only.setChecked(False);self.assertEqual(w.visible_rows(),list(range(7)));self.assertEqual([e['path'] for e in w.ordered()],paths)
   self.assertTrue(all(w.list.item(i) is item for i,item in enumerate(items)))
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_main_only_updates_on_unmark_undo_and_handles_empty_view(self):
  from PySide6.QtCore import QPoint
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(4):
    path=Path(d)/f'{i}.png';Image.new('RGB',(40,40),'red').save(path);paths.append(str(path))
   w=Window();w.add_paths(paths);w.set_main_for_ids([w.ordered()[i]['id'] for i in (1,3)],True)
   w.main_only.setChecked(True);self.assertEqual(w.list.currentRow(),1)
   w.toggle_main(False);self.assertEqual(w.visible_rows(),[3]);self.assertEqual(w.list.currentRow(),3)
   w.undo();self.assertEqual(w.visible_rows(),[1,3]);self.assertEqual(w.list.currentRow(),1)
   w.set_main_for_ids([e['id'] for e in w.ordered()],False);self.assertEqual(w.visible_rows(),[]);self.assertIsNone(w.current())
   self.assertEqual(w.list.target_at(QPoint(20,20)),4);w.list.selectAll();self.assertFalse(w.list.selectedItems())
   w.main_only.setChecked(False);self.assertEqual(w.visible_rows(),[0,1,2,3]);self.assertEqual([e['path'] for e in w.ordered()],paths)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_inline_cut_mode_keyboard_live_border_save_and_normal_preview(self):
  import json
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'target.png';Image.new('RGB',(400,200),'green').save(path)
   w=Window();w.show();w.activateWindow();w.add_paths([str(path)]);app.processEvents()
   editor=w.edit_cuts();self.assertIs(w.editor_stack.currentWidget(),editor);self.assertFalse(editor.isWindow())
   self.assertTrue(all(not action.isEnabled() for action in w.navigation_actions))
   editor.add_cell([.2,.2,.8,.8]);editor.paste();editor.set_mode('frame');app.processEvents()
   original=editor.cell()['rect'][:]
   QTest.keyClick(editor.canvas,Qt.Key.Key_Right);self.assertAlmostEqual(editor.cell()['rect'][0]-original[0],1/400)
   QTest.keyClick(editor.canvas,Qt.Key.Key_Down,Qt.KeyboardModifier.ShiftModifier);self.assertAlmostEqual(editor.cell()['rect'][1]-original[1],10/200)
   self.assertEqual(w.list.currentRow(),0);self.assertEqual(len(w.list.selectedItems()),1)
   w.undo();self.assertAlmostEqual(editor.cell()['rect'][1],original[1]);w.redo();self.assertAlmostEqual(editor.cell()['rect'][1]-original[1],10/200)
   editor.set_mode('move');old=editor.cell()['offset'][:];rect=editor.cell()['rect'][:]
   QTest.keyClick(editor.canvas,Qt.Key.Key_Left);self.assertEqual(editor.cell()['rect'],rect)
   self.assertAlmostEqual(editor.cell()['offset'][0]-old[0],-1/(400*(rect[2]-rect[0])))
   x,y=round(rect[0]*400),round((rect[1]+rect[3])/2*200)
   editor.border.setFocus();QTest.keyClick(editor.border,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(editor.border,'6')
   self.assertEqual(editor.canvas.pixmap.toImage().pixelColor(x,y).getRgb(),(0,0,0,255))
   QTest.keyClick(editor.border,Qt.Key.Key_Return);self.assertIs(w.cut_editor,editor);self.assertTrue(editor.canvas.hasFocus())
   editor.border.setValue(0);self.assertNotEqual(editor.canvas.pixmap.toImage().pixelColor(x,y).getRgb(),(0,0,0,255))
   editor.border.setValue(6);editor.final_preview.setChecked(True);self.assertFalse(editor.canvas.show_guides)
   project=str(Path(d)/'inline.photo.json');self.assertTrue(w.write_project(project));self.assertIs(w.cut_editor,editor)
   self.assertEqual(json.loads(Path(project).read_text(encoding='utf-8'))['images'][0]['composition']['cells'][0]['border'],6/400)
   w.finish_cut_mode(True);self.assertIsNone(w.cut_editor);self.assertIs(w.editor_stack.currentWidget(),w.splitter)
   self.assertTrue(all(action.isEnabled() for action in w.navigation_actions))
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   self.assertEqual(w.canvas.pixmap.toImage().pixelColor(x,y).getRgb(),(0,0,0,255))
   w.dirty=False;w.close()
 def test_inline_draft_cancel_close_and_apply_do_not_lose_edits(self):
  from unittest.mock import patch
  from PySide6.QtWidgets import QMessageBox
  from PySide6.QtGui import QCloseEvent
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'target.png';Image.new('RGB',(200,100),'red').save(path)
   w=Window();w.add_paths([str(path)]);w.write_project(str(Path(d)/'project.photo.json'))
   editor=w.edit_cuts();editor.border.setValue(4);self.assertTrue(w.has_cut_changes());self.assertNotIn('composition',w.current())
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Cancel):
    event=QCloseEvent();w.closeEvent(event);self.assertFalse(event.isAccepted())
   self.assertIs(w.cut_editor,editor);self.assertNotIn('composition',w.current())
   editor.reject();self.assertIsNone(w.cut_editor);self.assertNotIn('composition',w.current())
   editor=w.edit_cuts();editor.border.setValue(5);editor.apply()
   self.assertIsNone(w.cut_editor);self.assertEqual(w.current()['composition']['cells'][0]['border'],5/200)
   w.undo();self.assertNotIn('composition',w.current());w.redo();self.assertIn('composition',w.current())
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_cut_black_border_respects_gap_overlap_and_exports(self):
  from composition import pixel_asset,render_composition,validate_composition
  key,data=pixel_asset(Image.new('RGBA',(100,100),'red'))
  composition={'assets':{key:data},'cells':[{'rect':[.1,.1,.9,.9],'asset':key,'border':.02}],'gutter':.01,'freeform':True}
  base=Image.new('RGBA',(200,200),'green');result=render_composition(base,composition)
  self.assertEqual(result.getpixel((20,100)),(255,255,255,255));self.assertEqual(result.getpixel((22,100)),(0,0,0,255));self.assertEqual(result.getpixel((30,100)),(255,0,0,255))
  self.assertEqual(result.getpixel((10,100)),base.getpixel((10,100)))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'base.png';base.save(path);output=Path(d)/'export.png'
   export_image({'path':str(path),'regions':[],'composition':composition},output,'PNG')
   with Image.open(output) as exported:self.assertEqual(exported.convert('RGBA').tobytes(),result.tobytes())
  composition['cells'][0]['border']=float('nan')
  with self.assertRaises(ValueError):validate_composition(composition)
 def test_cut_black_border_is_per_cell_persists_and_undoes(self):
  from cut_editor import CutEditor
  from PySide6.QtGui import QIcon
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'base.png';Image.new('RGB',(400,200),'red').save(path)
   entry={'id':'s','path':str(path),'regions':[]};editor=CutEditor(entry,[entry],[QIcon()])
   editor.add_cell([.1,.1,.45,.9]);editor.paste();editor.border.setValue(6)
   self.assertEqual(editor.cell()['border'],.015);editor.undo();self.assertNotIn('border',editor.cell());editor.redo();self.assertEqual(editor.cell()['border'],.015)
   editor.add_cell([.55,.1,.9,.9]);self.assertEqual(editor.border.value(),0)
   self.assertNotIn('border',editor.cell());editor.canvas.active=0;editor.refresh();self.assertEqual(editor.border.value(),6)
   editor.apply();w=Window();w.add_paths([str(path)]);w.apply_composition(editor.composition)
   saved=str(Path(d)/'border.photo.json');w.write_project(saved);self.assertTrue(w.open_project(saved));self.assertEqual(w.current()['composition']['cells'][0]['border'],.015)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close();editor.reject()
 def test_last_project_reopens_and_new_project_requires_discard_confirmation(self):
  from unittest.mock import patch
  from PySide6.QtWidgets import QMessageBox
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'source.png';Image.new('RGB',(80,60),'red').save(path)
   w=Window();w.add_paths([str(path)]);project=str(Path(d)/'saved.photo.json');w.write_project(project)
   saved_id=w.current()['id'];w.dirty=False;w.close()
   reopened=Window();self.assertTrue(reopened.restore_last_project());self.assertEqual(reopened.project,project);self.assertEqual(reopened.current()['id'],saved_id)
   reopened.region_event(('add',[.1,.1,.5,.5]));before=len(reopened.history)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Cancel):self.assertFalse(reopened.new_project())
   self.assertEqual(reopened.project,project);self.assertEqual(len(reopened.history),before)
   with patch('main.QMessageBox.exec',return_value=QMessageBox.StandardButton.Save):self.assertTrue(reopened.new_project())
   self.assertIsNone(reopened.project);self.assertEqual(reopened.list.count(),0);self.assertFalse(reopened.history);self.assertFalse(reopened.redo_stack);self.assertFalse(reopened.dirty)
   self.assertFalse(reopened.restore_last_project())
   self.assertTrue(Path(project).is_file());import json
   self.assertTrue(json.loads(Path(project).read_text(encoding='utf-8'))['images'][0]['regions'])
   deadline=time.monotonic()+10
   while reopened.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   reopened.close()
 def test_last_project_tracks_open_not_recent_listing_and_restores_close_selection(self):
  import json
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(30):
    path=Path(d)/f'{i}.png';Image.new('RGB',(10,10),'red').save(path);paths.append(str(path))
   w=Window();w.show();w.add_paths(paths);project=str(Path(d)/'actual.photo.json');w.write_project(project)
   w.list.setCurrentRow(25);w.list.scrollToItem(w.list.item(25));app.processEvents();current=w.current()['id'];scroll=w.list.verticalScrollBar().value()
   unrelated=Path(d)/'other.photo.json';unrelated.write_text(json.dumps({'version':1,'images':[]}),encoding='utf-8');w.remember_project(unrelated)
   w.close();reopened=Window();reopened.show();app.processEvents();self.assertTrue(reopened.restore_last_project());app.processEvents()
   self.assertEqual(reopened.project,project);self.assertEqual(reopened.current()['id'],current);self.assertEqual(reopened.list.verticalScrollBar().value(),scroll)
   reopened.dirty=False;reopened.close()
 def test_last_project_upgrade_and_missing_path(self):
  import json
  from unittest.mock import patch
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'saved.photo.json';path.write_text(json.dumps({'version':1,'images':[]}),encoding='utf-8')
   w=Window();w.settings.remove('session/lastProject');w.remember_project(path)
   self.assertTrue(w.restore_last_project());self.assertEqual(w.project,str(path))
   w.settings.setValue('session/lastProject',str(Path(d)/'missing.photo.json'))
   with patch('main.QMessageBox.warning') as warning:self.assertFalse(w.restore_last_project());warning.assert_not_called()
   w.dirty=False;w.close()
 def test_free_cut_overlap_has_topmost_selection_and_borders(self):
  from cut_editor import CutEditor
  from composition import pixel_asset,render_composition
  from PySide6.QtGui import QIcon
  from PySide6.QtCore import Qt
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  red,red_data=pixel_asset(Image.new('RGBA',(100,100),'red'));blue,blue_data=pixel_asset(Image.new('RGBA',(100,100),'blue'))
  composition={'assets':{red:red_data,blue:blue_data},'freeform':True,'gutter':.02,'cells':[
   {'rect':[.1,.1,.8,.8],'asset':red},{'rect':[.4,.05,.95,.95],'asset':blue}]}
  image=Image.new('RGBA',(200,200),'green');result=render_composition(image,composition)
  self.assertEqual(result.getpixel((159,100)),(0,0,255,255))
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'target.png';image.save(path);entry={'id':'t','path':str(path),'regions':[],'composition':composition}
   editor=CutEditor(entry,[entry],[QIcon()]);editor.show();app.processEvents();editor.canvas.active=0;editor.set_mode('frame')
   point=editor.canvas.image_rect([.5,.4,.6,.5]).center().toPoint();QTest.mouseClick(editor.canvas,Qt.MouseButton.LeftButton,pos=point)
   self.assertEqual(editor.canvas.active,1);editor.canvas.active=0;editor.raise_cell();self.assertEqual(editor.cell()['asset'],red)
   editor.undo();self.assertEqual(editor.composition['cells'][0]['asset'],red);editor.reject()
 def test_source_selection_and_free_cut_use_actual_pointer_geometry(self):
  from cut_editor import CutEditor
  from composition import decode_asset
  from imaging import render_entry
  from PySide6.QtCore import Qt,QPoint
  from PySide6.QtGui import QIcon
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';target=Path(d)/'target.png'
   image=Image.new('RGB',(400,200),'red');image.paste('blue',(200,0,400,200));image.save(source)
   Image.new('RGB',(400,200),'green').save(target)
   entries=[{'id':'source','path':str(source),'regions':[]},{'id':'target','path':str(target),'regions':[]}]
   editor=CutEditor(entries[1],entries,[QIcon(),QIcon()]);editor.show();app.processEvents();editor.sources.setCurrentRow(0);app.processEvents()
   def point(canvas,x,y):
    return QPoint(round(canvas.target.x()+canvas.target.width()*x),round(canvas.target.y()+canvas.target.height()*y))
   sc=editor.source_canvas
   QTest.mousePress(sc,Qt.MouseButton.LeftButton,pos=point(sc,.1,.1));QTest.mouseMove(sc,point(sc,.4,.8));QTest.mouseRelease(sc,Qt.MouseButton.LeftButton,pos=point(sc,.4,.8))
   self.assertIsNotNone(sc.selection);box=editor.source_box();editor.copy_selection()
   copied=decode_asset(editor.clipboard[1]);self.assertEqual(copied.size,(box[2]-box[0],box[3]-box[1]));self.assertEqual(copied.getextrema(),((255,255),(0,0),(0,0),(255,255)))
   canvas=editor.canvas;editor.set_mode('draw')
   QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=point(canvas,.15,.2));QTest.mouseMove(canvas,point(canvas,.6,.7));QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=point(canvas,.6,.7));app.processEvents()
   self.assertEqual(len(editor.composition['cells']),1);rect=editor.cell()['rect'][:];self.assertAlmostEqual(rect[0],.15,delta=.005);self.assertLess(rect[2],.61)
   editor.paste();self.assertEqual(editor.composition['assets'][editor.cell()['asset']],editor.clipboard[1])
   result=render_entry(Image.new('RGBA',(400,200),'green'),dict(entries[1],composition=editor.composition))
   self.assertEqual(result.getpixel((100,80)),(255,0,0,255));self.assertEqual(result.getpixel((10,10)),(0,128,0,255))
   editor.set_mode('frame');corner=canvas.handles(rect)['se'].toPoint();before=len(editor.history)
   QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=corner);QTest.mouseMove(canvas,corner+QPoint(25,15));QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=corner+QPoint(25,15))
   changed=editor.cell()['rect'][:];self.assertGreater(changed[2],rect[2]);self.assertEqual(len(editor.history),before+1)
   editor.undo();self.assertEqual(editor.cell()['rect'],rect);editor.redo();self.assertEqual(editor.cell()['rect'],changed)
   center=canvas.image_rect(changed).center().toPoint()
   QTest.mousePress(canvas,Qt.MouseButton.LeftButton,pos=center);QTest.mouseMove(canvas,center+QPoint(15,10));QTest.mouseRelease(canvas,Qt.MouseButton.LeftButton,pos=center+QPoint(15,10))
   self.assertGreater(editor.cell()['rect'][0],changed[0]);self.assertAlmostEqual(editor.cell()['rect'][2]-editor.cell()['rect'][0],changed[2]-changed[0])
   editor.reject()
 def test_selected_crop_fills_original_resolution_and_supports_empty_layout(self):
  from cut_editor import CutEditor
  from composition import validate_composition
  from PySide6.QtGui import QIcon
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'original.png';image=Image.new('RGB',(400,200),'red');image.paste('blue',(200,0,400,200));image.save(path)
   entry={'id':'source','path':str(path),'regions':[]};editor=CutEditor(entry,[entry],[QIcon()])
   editor.source_canvas.selection=[.1,.1,.4,.9];editor.source_selected(editor.source_canvas.selection)
   editor.fill_original_resolution();editor.apply();validate_composition(editor.composition,check_images=True)
   output=Path(d)/'cropped.png';export_image(dict(entry,composition=editor.composition),output,'PNG')
   with Image.open(output) as result:self.assertEqual(result.size,(400,200));self.assertEqual(result.convert('RGB').getextrema(),((255,255),(0,0),(0,0)))
   editor.delete_cell();self.assertEqual(editor.composition['cells'],[]);validate_composition(editor.composition)
   editor.undo();self.assertEqual(len(editor.composition['cells']),1);editor.redo();editor.paste();self.assertEqual(len(editor.composition['cells']),1)
   editor.reject()
 def test_source_selection_handles_and_zoom_preserve_full_resolution_crop(self):
  from cut_editor import CutEditor
  from PySide6.QtCore import Qt,QPoint,QPointF
  from PySide6.QtGui import QIcon,QWheelEvent
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'source.png';Image.new('RGB',(3000,2000),'red').save(path)
   entry={'id':'s','path':str(path),'regions':[]};editor=CutEditor(entry,[entry],[QIcon()]);editor.show();app.processEvents()
   sc=editor.source_canvas;sc.selection=[.2,.2,.6,.6];corner=sc.handles(sc.selection)['se'].toPoint()
   QTest.mousePress(sc,Qt.MouseButton.LeftButton,pos=corner);QTest.mouseMove(sc,corner+QPoint(20,15));QTest.mouseRelease(sc,Qt.MouseButton.LeftButton,pos=corner+QPoint(20,15))
   self.assertGreater(sc.selection[2],.6);selected=sc.selection[:];box=editor.source_box()
   center=sc.image_rect(selected).center();event=QWheelEvent(center,QPointF(sc.mapToGlobal(center.toPoint())),QPoint(),QPoint(0,240),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
   QApplication.sendEvent(sc,event);self.assertEqual(sc.selection,selected);self.assertGreater(sc.view_zoom,1.)
   editor.copy_selection();from composition import decode_asset
   self.assertEqual(decode_asset(editor.clipboard[1]).size,(box[2]-box[0],box[3]-box[1]));editor.reject()
 def test_cut_composition_clips_pan_zoom_and_preserves_source(self):
  from composition import pixel_asset,render_composition
  source=Image.new('RGBA',(100,100),'red')
  from PIL import ImageDraw
  ImageDraw.Draw(source).rectangle((50,0,99,99),fill='blue')
  key,data=pixel_asset(source);base=Image.new('RGBA',(200,100),'green')
  composition={'assets':{key:data},'cells':[{'rect':[0.,0.,.5,1.],'asset':key,'scale':1.,'offset':[0.,0.]},{'rect':[.5,0.,1.,1.]}]}
  result=render_composition(base,composition)
  self.assertEqual(result.getpixel((25,50)),(255,0,0,255));self.assertEqual(result.getpixel((75,50)),(0,0,255,255))
  self.assertEqual(result.getpixel((125,50)),base.getpixel((125,50)))
  composition['cells'][0]['offset']=[.5,0.]
  moved=render_composition(base,composition);self.assertEqual(moved.getpixel((75,50)),(255,0,0,255))
  self.assertEqual(moved.getpixel((5,50)),(255,255,255,255));self.assertEqual(moved.getpixel((125,50)),base.getpixel((125,50)))
  composition['cells'][0].update(scale=2.,offset=[0.,0.])
  scaled=render_composition(base,composition);self.assertEqual(scaled.getpixel((125,50)),base.getpixel((125,50)))
  self.assertEqual(source.getpixel((75,50)),(0,0,255,255))
 def test_cut_copy_is_flattened_and_export_survives_removed_source(self):
  from composition import decode_asset
  from imaging import render_entry
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';target=Path(d)/'target.png'
   Image.effect_noise((200,100),100).convert('RGB').save(source,pnginfo=None);Image.new('RGB',(200,100),'green').save(target)
   w=Window();w.add_paths([str(source),str(target)])
   w.current()['regions']=[{'rect':[0.,0.,1.,1.],'strength':100}]
   from imaging import read_pixels
   expected=render_entry(read_pixels(source),w.current())
   w.copy_for_cut();key,data=w.cut_clipboard;self.assertEqual(decode_asset(data).tobytes(),expected.tobytes());self.assertFalse(decode_asset(data).info)
   w.list.setCurrentRow(1);composition={'assets':{key:data},'cells':[{'rect':[0.,0.,1.,1.],'asset':key,'scale':1.,'offset':[0.,0.]}]}
   w.apply_composition(composition);self.assertIn('composition',w.current());w.undo();self.assertNotIn('composition',w.current());w.redo()
   saved=str(Path(d)/'cuts.photo.json');w.write_project(saved)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   source.unlink();w.dirty=False;self.assertTrue(w.open_project(saved));self.assertEqual(w.current()['path'],str(target))
   output=Path(d)/'out.png';export_image(w.current(),output,'PNG')
   with Image.open(output) as result:self.assertEqual(result.convert('RGBA').tobytes(),expected.tobytes());self.assertFalse(result.info)
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_cut_editor_pointer_split_paste_move_copy_and_cancel(self):
  from cut_editor import CutEditor
  from PySide6.QtCore import Qt,QPoint,QPointF
  from PySide6.QtGui import QIcon,QWheelEvent
  from PySide6.QtTest import QTest
  import copy
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   source=Path(d)/'source.png';target=Path(d)/'target.png'
   Image.new('RGB',(120,80),'red').save(source);Image.new('RGB',(200,120),'green').save(target)
   entries=[{'id':'source','path':str(source),'regions':[]},{'id':'target','path':str(target),'regions':[]}]
   original=copy.deepcopy(entries);editor=CutEditor(entries[1],entries,[QIcon(),QIcon()]);editor.show();app.processEvents()
   editor.sources.setCurrentRow(0);editor.copy_source();self.assertIsNotNone(editor.clipboard)
   editor.set_mode('vertical');rect=editor.canvas.target;center=rect.center().toPoint()
   QTest.mouseClick(editor.canvas,Qt.MouseButton.LeftButton,pos=center);app.processEvents()
   self.assertEqual(len(editor.composition['cells']),2);editor.paste();self.assertIn('asset',editor.composition['cells'][0])
   start=QPoint(round(rect.x()+rect.width()*.25),round(rect.center().y()));end=start+QPoint(25,15)
   QTest.mousePress(editor.canvas,Qt.MouseButton.LeftButton,pos=start);QTest.mouseMove(editor.canvas,end);QTest.mouseRelease(editor.canvas,Qt.MouseButton.LeftButton,pos=end)
   app.processEvents();self.assertNotEqual(editor.cell()['offset'],[0.,0.]);offset=editor.cell()['offset'][:]
   editor.undo();self.assertEqual(editor.cell()['offset'],[0.,0.]);editor.redo();self.assertEqual(editor.cell()['offset'],offset)
   wheel=QWheelEvent(QPointF(start),QPointF(editor.canvas.mapToGlobal(start)),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
   QApplication.sendEvent(editor.canvas,wheel);self.assertGreater(editor.cell()['scale'],1.)
   editor.fit(False);self.assertLessEqual(editor.cell()['scale'],1.)
   editor.copy_region([0.,0.,.5,1.]);editor.canvas.active=1;editor.paste();self.assertIn('asset',editor.cell())
   editor.remove_layer();self.assertNotIn('asset',editor.cell());editor.undo();self.assertIn('asset',editor.cell())
   editor.reject();self.assertEqual(entries,original)
 def test_cut_data_validation_rejects_invalid_geometry_and_missing_assets(self):
  from composition import validate_composition,empty_composition
  validate_composition(empty_composition())
  for change in [{'rect':[0,0,float('nan'),1]},{'rect':[0,0,1,1],'asset':'missing'},{'rect':[0,0,1,1],'asset':'x','scale':float('inf')}]:
   with self.assertRaises(ValueError):validate_composition({'assets':{'x':'unused'},'cells':[change]})
 def test_cut_mosaic_remains_last_and_gap_is_exported(self):
  from composition import pixel_asset,render_composition
  from imaging import render_entry,render_regions
  source=Image.effect_noise((200,100),100).convert('RGBA');key,data=pixel_asset(source)
  base=Image.new('RGBA',(200,100),'green')
  composition={'assets':{key:data},'cells':[{'rect':[0.,0.,.5,1.],'asset':key},{'rect':[.5,0.,1.,1.],'asset':key}],'gutter':.03}
  composed=render_composition(base,composition)
  self.assertEqual(composed.getpixel((100,50)),(255,255,255,255))
  regions=[{'rect':[0.,0.,.4,1.],'strength':100}]
  result=render_entry(base,{'regions':regions,'composition':composition})
  self.assertEqual(result.tobytes(),render_regions(composed,regions).tobytes())
  self.assertNotEqual(result.crop((0,0,70,90)).tobytes(),composed.crop((0,0,70,90)).tobytes())
 def test_mosaic_repeated_strokes_and_order_do_not_change_strength(self):
  from imaging import render_regions
  image=Image.effect_noise((503,397),100).convert('RGBA')
  original=image.tobytes()
  a={'kind':'brush','rect':[.1,.1,.7,.7],'points':[[.3,.3],[.6,.5]],'radius':.08,'strength':24}
  b=dict(a,points=[[.4,.4],[.7,.6]],strength=8)
  first=render_regions(image,[a,b])
  self.assertEqual(first.tobytes(),render_regions(image,[a,b,a,b]*10).tobytes())
  self.assertEqual(first.tobytes(),render_regions(image,[b,a]).tobytes())
  self.assertEqual(first.getpixel((251,190)),render_regions(image,[a]).getpixel((251,190)))
  self.assertEqual(image.tobytes(),original)
 def test_mosaic_grid_stays_fixed_across_stroke_extent_and_image_edges(self):
  from imaging import render_regions,grid_mosaic
  image=Image.effect_noise((503,397),100).convert('RGBA')
  short={'kind':'brush','rect':[.25,.25,.35,.35],'points':[[.3,.3]],'radius':.05,'strength':24}
  long=dict(short,points=[[.3,.3],[.8,.7]])
  self.assertEqual(render_regions(image,[short]).crop((140,110,160,130)).tobytes(),render_regions(image,[long]).crop((140,110,160,130)).tobytes())
  full=grid_mosaic(image,(0,0,503,397),12)
  for box in [(17,23,80,99),(480,370,503,397),(0,0,2,2)]:
   self.assertEqual(full.crop(box).tobytes(),grid_mosaic(image,box,12).tobytes())
  white=Image.new('RGBA',(503,397),'white')
  self.assertEqual(grid_mosaic(white,(480,370,503,397),12).getextrema(),white.getextrema())
 def test_mosaic_feather_preserves_opaque_core_and_legacy_region_data(self):
  import copy
  from PIL import ImageDraw
  from imaging import render_regions,grid_mosaic
  image=Image.effect_noise((400,400),100).convert('RGBA')
  old={'kind':'brush','rect':[.45,.45,.55,.55],'points':[[.5,.5]],'radius':.05,'strength':20}
  before=copy.deepcopy(old);result=render_regions(image,[old]);self.assertEqual(old,before)
  mask=Image.new('L',image.size);ImageDraw.Draw(mask).ellipse((180,180,220,220),fill=255)
  expected=grid_mosaic(image,(0,0,400,400),8)
  self.assertEqual(Image.composite(result,image,mask).tobytes(),Image.composite(expected,image,mask).tobytes())
  self.assertEqual(result.getpixel((20,20)),image.getpixel((20,20)))
 def test_undo_redo_preserves_all_current_tool_settings(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'image.png';Image.new('RGB',(80,60),'red').save(path)
   w=Window();w.add_paths([str(path)])
   w.region_event(('add',[.1,.1,.5,.5]));w.strength.setValue(33)
   w.region_event(('add',[.5,.5,.9,.9]));w.strength.setValue(77)
   w.tool.setCurrentIndex(1);w.brush_size.setValue(123);w.clone_softness.setValue(68)
   settings=(w.strength.value(),w.brush_size.value(),dict(w.tool_sizes),w.canvas.brush_radius,w.tool.currentIndex(),w.clone_softness.value())
   for action in [w.undo,w.undo,w.redo,w.redo]:
    action();self.assertEqual((w.strength.value(),w.brush_size.value(),dict(w.tool_sizes),w.canvas.brush_radius,w.tool.currentIndex(),w.clone_softness.value()),settings)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_project_restores_last_selected_thumbnail_and_scroll(self):
  app=QApplication.instance() or QApplication([])
  with tempfile.TemporaryDirectory() as d:
   paths=[]
   for i in range(80):
    path=Path(d)/f'{i}.png';Image.new('RGB',(10,10),'red').save(path);paths.append(str(path))
   w=Window();w.show();w.add_paths(paths);app.processEvents()
   w.list.setCurrentRow(70);w.list.scrollToItem(w.list.item(70));app.processEvents()
   current=w.current()['id'];scroll=w.list.verticalScrollBar().value()
   project=str(Path(d)/'test.photo.json');self.assertTrue(w.write_project(project))
   w.list.setCurrentRow(0);w.list.scrollToTop();self.assertTrue(w.open_project(project));app.processEvents()
   self.assertEqual(w.current()['id'],current);self.assertEqual(w.list.verticalScrollBar().value(),scroll)
   deadline=time.monotonic()+10
   while w.jobs and time.monotonic()<deadline:app.processEvents();time.sleep(.001)
   w.dirty=False;w.close()
 def test_numeric_control_text_entry_and_wheel_steps(self):
  from main import NumericControl
  from PySide6.QtCore import Qt,QPoint,QPointF
  from PySide6.QtGui import QWheelEvent
  from PySide6.QtTest import QTest
  app=QApplication.instance() or QApplication([])
  slider=NumericControl();slider.setRange(2,100);slider.show();app.processEvents()
  slider.setFocus();QTest.keyClick(slider,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(slider,'76')
  self.assertEqual(slider.value(),76)
  def wheel(delta):
   event=QWheelEvent(QPointF(200,15),QPointF(slider.mapToGlobal(QPoint(200,15))),QPoint(),QPoint(0,delta),Qt.MouseButton.NoButton,Qt.KeyboardModifier.ControlModifier,Qt.ScrollPhase.NoScrollPhase,False)
   QApplication.sendEvent(slider,event)
  slider.setValue(20);wheel(120);self.assertEqual(slider.value(),21)
  wheel(-120);self.assertEqual(slider.value(),20)
  wheel(60);self.assertEqual(slider.value(),20);wheel(60);self.assertEqual(slider.value(),21)
  slider.setValue(100);wheel(120);self.assertEqual(slider.value(),100)
  slider.close()
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
   w.strength.setFocus();QTest.keyClick(w.strength,Qt.Key.Key_A,Qt.KeyboardModifier.ControlModifier);QTest.keyClicks(w.strength,'80');QTest.keyClick(w.strength,Qt.Key.Key_Return)
   app.processEvents()
   self.assertEqual(w.current()['regions'][0]['strength'],80)
   self.assertNotEqual(before,w.canvas.pixmap.toImage())
   self.assertTrue(w.list.hasFocus())
   QTest.keyClick(w.list,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier); app.processEvents()
   self.assertEqual(w.list.currentRow(),1)
   self.assertEqual(w.current()['regions'][0]['strength'],20)
   QTest.keyClick(w.list,Qt.Key.Key_Z,Qt.KeyboardModifier.ControlModifier); app.processEvents()
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
   self.assertTrue(w.list.viewport().acceptDrops())
   QApplication.sendEvent(w.list.viewport(),enter);self.assertTrue(enter.isAccepted());self.assertEqual(w.list.drop_target,1)
   move=QDragMoveEvent(pos,Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   QApplication.sendEvent(w.list.viewport(),move);self.assertTrue(move.isAccepted());self.assertEqual(w.list.drop_target,1)
   QApplication.sendEvent(w.list.viewport(),QDragLeaveEvent());self.assertIsNone(w.list.drop_target)
   enter=QDragEnterEvent(pos,Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   QApplication.sendEvent(w.list.viewport(),enter)
   drop=QDropEvent(QPointF(pos),Qt.DropAction.CopyAction|Qt.DropAction.MoveAction,mime,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
   history=len(w.history);QApplication.sendEvent(w.list.viewport(),drop)
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
    w.strength.setValue(w.strength.value())
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
