"""Crash recovery is separate from explicit project saves."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import uuid
from imaging import validate_edits


def validate_document(data):
    if not isinstance(data,dict) or data.get('version')!=1 or not isinstance(data.get('images'),list):raise ValueError('잘못된 복구 작업')
    ids=set()
    for entry in data['images']:
        if not isinstance(entry,dict) or not isinstance(entry.get('id'),str) or entry['id'] in ids or not isinstance(entry.get('path'),str):raise ValueError('잘못된 복구 이미지')
        ids.add(entry['id']);validate_edits(entry)
    export=data.get('export',{})
    if not isinstance(export,dict) or not isinstance(export.get('name',''),str) or not isinstance(export.get('follow_project_name',False),bool):raise ValueError('잘못된 복구 출력 설정')


def atomic_text(path,text):
    temporary=path.with_name(path.name+'.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        stream.write(text);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


class RecoveryStore:
    def __init__(self,directory):
        self.directory=Path(directory);self.session=uuid.uuid4().hex;self.digest=None

    @classmethod
    def for_settings(cls,settings):
        file=Path(settings.fileName())
        if file.suffix.lower() in ('.ini','.conf'):return cls(file.parent/'recovery')
        return cls(Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'PhotoOrganizer'/'Photo'/'recovery')

    @property
    def current(self):return self.directory/(self.session+'.current.json')
    @property
    def previous(self):return self.directory/(self.session+'.previous.json')

    def write(self,data,project,name):
        content=json.dumps({'data':data,'project':project,'name':name},ensure_ascii=False,separators=(',',':'))
        digest=hashlib.sha256(content.encode('utf-8')).hexdigest()
        if digest==self.digest:return False
        self.directory.mkdir(parents=True,exist_ok=True)
        if self.current.is_file():
            try:
                old=self.current.read_text(encoding='utf-8')
                old_record=json.loads(old)
                if not isinstance(old_record,dict) or old_record.get('format')!=1:raise ValueError('invalid recovery')
                atomic_text(self.previous,old)
            except (OSError,ValueError,TypeError,KeyError):pass
        record={'format':1,'captured_at':datetime.now().astimezone().isoformat(), 'data':data,'project':project,'name':name}
        atomic_text(self.current,json.dumps(record,ensure_ascii=False,separators=(',',':')))
        self.digest=digest;return True

    @staticmethod
    def read(path):
        record=json.loads(Path(path).read_text(encoding='utf-8'))
        if not isinstance(record,dict) or record.get('format')!=1 or not isinstance(record.get('name'),str) or not isinstance(record.get('captured_at'),str) or (record.get('project') is not None and not isinstance(record['project'],str)):raise ValueError('잘못된 복구 파일')
        validate_document(record['data']);return record

    def candidates(self):
        records=[]
        if not self.directory.is_dir():return records
        sessions={path.name.split('.')[0] for path in self.directory.glob('*.json')}
        for session in sessions:
            for kind in ('current','previous'):
                path=self.directory/(session+'.'+kind+'.json')
                try:
                    record=self.read(path);records.append((path,record));break
                except (OSError,ValueError,TypeError,KeyError):continue
        return sorted(records,key=lambda item:item[1]['captured_at'],reverse=True)

    def adopt(self,path):
        self.session=Path(path).name.split('.')[0];self.digest=None

    def clear(self):
        for path in (self.current,self.previous):path.unlink(missing_ok=True)
        self.digest=None
