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
if __name__=='__main__':unittest.main()
