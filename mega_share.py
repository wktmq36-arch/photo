"""Encrypted export packages and the official MEGAcmd client.

The app never receives a MEGA account password: MEGAcmd owns its login session.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import re
import secrets
import shutil
import string
import subprocess
import tempfile
import time

import pyzipper
from exporting import linked


def today_suffix():
    return datetime.now(timezone(timedelta(hours=9))).strftime('%y%m%d')


def find_client(configured=''):
    candidates=[configured,shutil.which('MegaClient.exe') or '']
    for variable in ('LOCALAPPDATA','ProgramFiles','ProgramFiles(x86)'):
        root=os.environ.get(variable)
        if root:candidates.append(str(Path(root)/'MEGAcmd'/'MegaClient.exe'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and Path(candidate).name.lower()=='megaclient.exe':
            return str(Path(candidate).resolve())
    return None


class ShareCancelled(RuntimeError):pass


class MegaClient:
    def __init__(self,executable,cancel_event=None,progress=None):
        self.executable=str(executable);self.cancel_event=cancel_event;self.progress=progress

    def _execute(self,command,timeout):
        # A newly launched MEGAcmd server can inherit stdout. A file avoids
        # communicate() waiting for EOF until that background server exits.
        with tempfile.TemporaryFile() as output:
            process=subprocess.Popen(command,shell=False,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            start=time.monotonic()
            while process.poll() is None:
                cancelled=self.cancel_event is not None and self.cancel_event.is_set()
                expired=time.monotonic()-start>timeout
                if cancelled or expired:
                    process.kill();process.wait(timeout=5);output.seek(0);text=output.read().decode('utf-8',errors='replace')
                    if command[1]=='put':
                        tag=re.search(r'Tag\s*=\s*(\d+)',text,re.I)
                        if tag:
                            try:MegaClient(self.executable).run('transfers','-c',tag.group(1),timeout=10)
                            except Exception:pass
                    if cancelled:raise ShareCancelled('MEGA 공유를 취소했습니다.')
                    raise RuntimeError('MEGA 응답 시간이 초과됐습니다. 연결을 확인한 뒤 재시도하세요.')
                try:process.wait(timeout=.15)
                except subprocess.TimeoutExpired:pass
            output.seek(0)
            return subprocess.CompletedProcess(command,process.returncode,output.read().decode('utf-8',errors='replace'))

    def run(self,*args,timeout=120):
        if self.cancel_event is not None and self.cancel_event.is_set():raise ShareCancelled('MEGA 공유를 취소했습니다.')
        phases={'whoami':'MEGA 로그인 확인','mkdir':'MEGA 폴더 확인','ls':'MEGA 폴더 확인','find':'MEGA 파일 이름 확인','put':'MEGA ZIP 업로드','export':'MEGA 공유 링크 생성'}
        if self.progress:self.progress(phases.get(args[0],'MEGA 응답 확인'))
        result=self._execute([self.executable,*args],timeout)
        if result.returncode:raise RuntimeError(f'MEGA {args[0]} 실패: {result.stdout[-1800:].strip()}')
        return result.stdout

    def check_login(self):
        self.run('whoami')

    def ensure_folder(self,remote_folder):
        try:self.run('mkdir','-p',remote_folder)
        except RuntimeError:
            # Some MEGAcmd versions report an error for an existing directory
            # even with -p. Continue only if the exact folder is accessible.
            self.run('ls',remote_folder+'/')

    def archive_names(self,remote_folder='/Reward'):
        self.ensure_folder(remote_folder)
        output=self.run('find',remote_folder,'--type=f')
        return {line.strip().rsplit('/',1)[-1] for line in output.splitlines() if line.strip().startswith(remote_folder+'/')}

    def upload_and_link(self,archive,remote_folder):
        self.ensure_folder(remote_folder)
        self.run('put','--print-tag-at-start',str(Path(archive).resolve()),remote_folder+'/',timeout=86400)
        remote_path=remote_folder+'/'+Path(archive).name
        try:output=self.run('export',remote_path)
        except RuntimeError:output=''
        if not re.search(r'https://mega\.nz/file/[A-Za-z0-9_-]+#[A-Za-z0-9_-]+',output):
            output=self.run('export','-a','-f',remote_path)
        match=re.search(r'https://mega\.nz/file/[A-Za-z0-9_-]+#[A-Za-z0-9_-]+',output)
        if not match:raise RuntimeError('업로드 후 MEGA 공유 링크를 확인하지 못했습니다. 재시도로 링크를 다시 확인할 수 있습니다.')
        return match.group(0)


def write_state(path,state):
    path=Path(path);temp=path.with_name(path.name+'.tmp')
    temp.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)


def create_package(source,stem,day=None,remote_names=(),cancel_event=None):
    source=Path(source)
    if not source.is_dir() or linked(source):
        raise ValueError('정상적인 원본용 출력 폴더를 선택하세요.')
    if not source.name.endswith('_uncen'):raise ValueError('원본용(_uncen) 폴더를 선택하세요.')
    if not stem or Path(stem).name!=stem or stem in ('.','..') or any(c in stem for c in '<>:"/\\|?*') or any(ord(c)<32 for c in stem):
        raise ValueError('잘못된 작업 이름입니다.')
    files=[]
    for path in source.rglob('*'):
        if linked(path):raise ValueError('연결 파일/폴더는 압축하지 않습니다.')
        if path.is_file():files.append(path)
    if not files:raise ValueError('원본용 폴더가 비어 있습니다. 원본용을 먼저 내보내세요.')
    base=f'{stem}_{day or today_suffix()}';index=1;remote_names=set(remote_names)
    while True:
        name=base if index==1 else f'{base}_{index}'
        archive=source.parent/(name+'.zip');text=source.parent/(name+'.txt');state_path=source.parent/(name+'.upload.json')
        if archive.exists() or text.exists() or archive.name in remote_names:index+=1;continue
        try:
            with state_path.open('x',encoding='utf-8') as stream:stream.write('{}')
            break
        except FileExistsError:index+=1
    password=''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(20))
    state={'version':1,'archive':str(archive.resolve()),'text':str(text.resolve()),'password':password,
           'remote_folder':'/Reward','status':'compressing'}
    write_state(state_path,state)
    temporary=archive.with_suffix('.zip.tmp')
    try:
        with pyzipper.AESZipFile(str(temporary),'w',compression=pyzipper.ZIP_STORED,encryption=pyzipper.WZ_AES,allowZip64=True) as output:
            output.setpassword(password.encode('ascii'));output.setencryption(pyzipper.WZ_AES,nbits=256)
            for path in sorted(files):
                if cancel_event is not None and cancel_event.is_set():raise ShareCancelled('암호 압축을 취소했습니다.')
                output.write(str(path),arcname=(Path(stem)/path.relative_to(source)).as_posix())
        temporary.replace(archive);state['status']='ready';write_state(state_path,state)
    except Exception:
        temporary.unlink(missing_ok=True);raise
    return state_path


def upload_package(state_path,client):
    state_path=Path(state_path);state=json.loads(state_path.read_text(encoding='utf-8'))
    if state.get('version')!=1 or state.get('status') not in ('ready','failed','complete'):
        raise ValueError('완성된 압축 작업 파일을 선택하세요.')
    archive=Path(state['archive']);text=Path(state['text'])
    # A retry file cannot direct writes outside its own output directory.
    if archive.parent.resolve()!=state_path.parent.resolve() or text.parent.resolve()!=state_path.parent.resolve() or archive.suffix!='.zip' or text.suffix!='.txt':
        raise ValueError('잘못된 압축 작업 경로입니다.')
    if (state.get('remote_folder')!='/Reward' and not re.fullmatch(r'/PhotoExports/[a-f0-9]{32}',state.get('remote_folder',''))) or not re.fullmatch(r'[A-Za-z0-9]{20}',state.get('password','')):
        raise ValueError('잘못된 업로드 작업 데이터입니다.')
    if not archive.is_file():raise ValueError('압축 파일이 없습니다.')
    try:
        client.check_login()
        link=state.get('link')
        if not link:
            link=client.upload_and_link(archive,state['remote_folder'])
            state['link']=link;write_state(state_path,state)
        if not re.fullmatch(r'https://mega\.nz/file/[A-Za-z0-9_-]+#[A-Za-z0-9_-]+',link):raise ValueError('잘못된 공유 링크입니다.')
        content=f'Download Link :\n{link}\n\nPassword : \n{state["password"]}\n'
        if text.exists() and text.read_text(encoding='utf-8')!=content:raise ValueError('기존 TXT 파일 내용이 달라 덮어쓰지 않았습니다.')
        if not text.exists():
            with text.open('x',encoding='utf-8',newline='\n') as stream:stream.write(content)
        state['status']='complete';write_state(state_path,state)
        return str(text)
    except Exception:
        state['status']='failed';write_state(state_path,state);raise
