from pathlib import Path
import subprocess
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QPushButton,QFileDialog,QMessageBox
from mega_share import find_client


class MegaSettings(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent);self.setWindowTitle('MEGA 연결');self.resize(560,220)
        self.settings=settings;layout=QVBoxLayout(self)
        intro=QLabel('1. 공식 MEGAcmd를 설치합니다.\n2. 아래 로그인 창에서 login을 입력하고 계정으로 로그인합니다.\n3. Photo의 MEGA로 공유 버튼을 사용합니다.\n계정 비밀번호는 Photo에 입력하거나 저장하지 않습니다.')
        intro.setWordWrap(True);layout.addWidget(intro)
        row=QHBoxLayout();layout.addLayout(row)
        self.path=QLineEdit(find_client(str(settings.value('mega/client',''))) or '');self.path.setPlaceholderText('MEGAcmd 폴더의 MegaClient.exe');row.addWidget(self.path,1)
        browse=QPushButton('찾기');browse.clicked.connect(self.browse);row.addWidget(browse)
        row=QHBoxLayout();layout.addLayout(row)
        install=QPushButton('공식 설치 페이지');install.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://mega.nz/cmd')));row.addWidget(install)
        login=QPushButton('MEGA 로그인 창');login.clicked.connect(self.login);row.addWidget(login)
        save=QPushButton('저장');save.clicked.connect(self.save);row.addWidget(save)
        note=QLabel('업로드 위치: MEGA /Reward 바로 아래 · 압축 파일과 TXT는 내보낸 폴더 옆에 보관\n실패하면 ZIP과 .upload.json을 유지하고 메뉴에서 업로드 재시도 가능')
        note.setWordWrap(True);layout.addWidget(note)

    def browse(self):
        path,_=QFileDialog.getOpenFileName(self,'MegaClient.exe 선택',self.path.text(),'MEGAcmd client (MegaClient.exe)')
        if path:self.path.setText(path)

    def save(self):
        client=find_client(self.path.text())
        if not client:QMessageBox.warning(self,'MEGAcmd 필요','MEGAcmd를 설치하고 MegaClient.exe를 지정하세요.');return
        self.settings.setValue('mega/client',client);self.accept()

    def login(self):
        client=find_client(self.path.text())
        shell=Path(client).with_name('MEGAcmdShell.exe') if client else None
        if not shell or not shell.is_file():QMessageBox.warning(self,'MEGAcmd 필요','먼저 공식 MEGAcmd를 설치하고 실행 파일을 지정하세요.');return
        try:subprocess.Popen([str(shell)],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))
        except OSError as exc:QMessageBox.warning(self,'로그인 창 실행 실패',str(exc))
